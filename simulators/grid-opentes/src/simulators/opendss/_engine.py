"""Ciclo de vida do motor OpenDSS: compilacao, solucao e invalidacao de cache.

Camada mais baixa do wrapper. Detem o handle ``dss``, o cache da solucao e o
tratamento de erros; leitura e escrita se apoiam nela.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import pathlib
from typing import Any

from . import opendss_generator, opendss_pv, opendss_regulator
from ._types import OpenDSSException


class EngineMixin:
    """Compilacao, execucao e invalidacao de cache.

    Espera de quem compoe: ``self.dss``, ``self._snapshot``,
    ``self._node_index``, ``self.fail_on_error``, ``self._tolerance`` e
    ``self._max_iterations``. Preenche
    ``self._declared_pv_conversion`` e ``self._declared_generator_band`` a cada
    compilacao.
    """

    def warn_if_engine_already_in_use(self) -> None:
        """Avisa se já existe outro circuito compilado no mesmo motor.

        Todas as instâncias de ``py_dss_interface.DSS()`` compartilham **um
        único** motor OpenDSS no processo: compilar um segundo circuito
        repõe o primeiro, e o wrapper anterior passa a ler o circuito novo sem
        qualquer erro. Como isso é invisível, é sinalizado aqui.

        Para de fato isolar dois circuitos, cada um precisa de sua própria cópia
        da DLL (``py_dss_interface.DSS(dll_path)``).
        """
        existing = self.dss.circuit.name
        if existing:
            self.print(
                f"[AVISO] O motor OpenDSS ja tem o circuito '{existing}' compilado. "
                "Todas as instancias DSS() compartilham o mesmo motor, entao o "
                "circuito anterior sera substituido e qualquer wrapper que o use "
                "passara a ler este. Para dois circuitos simultaneos, cada um "
                "precisa de sua propria copia da DLL."
            )

    def compile_circuit(self, topofile: str | os.PathLike, base_dir: pathlib.Path) -> None:
        """Compila o arquivo ``.dss`` do circuito, falhando alto se algo der errado.

        Instanciar ``py_dss_interface.DSS()`` **muda o diretório de trabalho do
        processo** para o ``DataPath`` que o motor guardou — possivelmente de
        outra sessão, até de outro projeto. A partir daí, qualquer caminho
        relativo que o Python resolva (``Path.resolve()``, ``Path.cwd()``) sai
        errado em silêncio, produzindo caminhos duplicados como
        ``.../data/13Bus/data/13Bus/master.dss``. E o ``Redirect`` de um arquivo
        inexistente não levanta erro: a simulação segue com o circuito vazio.

        Daí as três defesas: caminhos relativos são resolvidos contra
        *base_dir* (capturado antes de o motor existir), a existência do
        arquivo é conferida antes do ``Redirect``, e o diretório de trabalho é
        devolvido ao original no fim.

        Args:
            topofile: Caminho do arquivo ``.dss`` master a compilar. É um
                arquivo só: o motor OpenDSS é único no processo (veja
                :meth:`warn_if_engine_already_in_use`), então cada wrapper
                atende a exatamente um circuito. Arquivos auxiliares do
                alimentador entram pelos ``Redirect`` do próprio master.
            base_dir: Diretório contra o qual resolver caminhos relativos.

        Raises:
            OpenDSSException: Se o arquivo não existe, se o ``Redirect``
                reporta erro, ou se ao final o circuito não tem barras.
        """
        try:
            path = pathlib.Path(topofile).expanduser()
            if not path.is_absolute():
                path = (base_dir / path).resolve()

            if not path.is_file():
                self.fail(f'DSS file not found: "{path}"')
                return

            self.dss.text(f"set datapath={path.parent}")
            with self._dialogs_while_compiling():
                status = self.dss.text(f'Redirect "{path}"')

            if status and ("not found" in status.lower() or "error" in status.lower()):
                self.fail(f'Redirect failed for "{path}": {status}')

            if self.dss.circuit.num_buses == 0:
                self.fail(
                    f'No circuit was compiled from "{path}". The circuit has no '
                    "buses — check the file path and its contents."
                )

            self._after_compile()
        finally:
            os.chdir(base_dir)

    @contextlib.contextmanager
    def _dialogs_while_compiling(self):
        """Liga as caixas de diálogo do OpenDSS só enquanto o ``.dss`` compila.

        Com elas desligadas (``AllowForms``), o erro de um comando volta como
        texto e código, que :meth:`run_command` confere. Mas o ``Redirect`` de
        um arquivo informa só o erro da **última** linha executada — medido: um
        parâmetro inexistente no meio do arquivo, seguido de linhas boas,
        termina com código 0 e status vazio. Sem a caixa, um erro de digitação
        no ``.dss`` passaria em silêncio.

        Fora da compilação elas ficam desligadas: uma caixa no meio do estudo
        trava a execução até alguém clicar, o que anularia o
        ``fail_on_error=False``. O estado é global do motor — uma instância nova
        de ``DSS()`` herda o que a anterior deixou —, por isso é religado a cada
        compilação, e não uma vez só.
        """
        self.dss.dssinterface.allow_forms = True
        try:
            yield
        finally:
            self.dss.dssinterface.allow_forms = False

    def _after_compile(self) -> None:
        """Ajustes que todo ``Compile`` desfaz e que, por isso, seguem cada um.

        O ``Compile`` do OpenDSS repõe o critério de convergência no padrão e
        traz de volta o que o ``.dss`` declara para PVSystems, Generators e
        RegControls. Reunidos aqui para que :meth:`compile_circuit` e
        :meth:`redirect` não possam divergir sobre o que reaplicar.
        """
        self.apply_solution_settings()
        self._idealize_pvsystems()
        self._relax_generators()
        # Antes da primeira solução: os taps só mudam por controlador externo.
        opendss_regulator.freeze_regulators(self.dss)

    def apply_solution_settings(self) -> None:
        """(Re)aplica ``tolerance`` e ``max_iterations`` ao motor.

        Precisa ser chamada depois de **toda** compilação, e não uma vez no
        construtor: o ``Compile`` do OpenDSS repõe os dois nos padrões dele —
        medido, ``tolerance`` volta a 1e-4 e ``max_iterations`` a 15. Um wrapper
        que recompilasse o circuito perderia o ajuste sem nada avisando, e a
        próxima solução seria resolvida com uma precisão que ninguém pediu.

        Os valores pedidos ficam guardados na instância justamente para
        sobreviver a essas reposições. ``None`` significa "não mexer", de modo
        que quem não pede nada continua com o padrão do motor.
        """
        if self._tolerance is not None:
            self.dss.solution.tolerance = self._tolerance
        if self._max_iterations is not None:
            self.dss.solution.max_iterations = self._max_iterations

    def _idealize_pvsystems(self) -> None:
        """Põe a conversão DC/AC ideal em todo PVSystem do circuito recém-compilado.

        Faz parte do carregamento, e não da criação das entidades: assim a
        primeira solução, a do construtor, já sai com o modelo que a
        co-simulação usa. E, como o ``Compile`` traz de volta as curvas
        declaradas, é reaplicada a cada compilação, como
        :meth:`apply_solution_settings`.

        Roda uma vez por compilação, e só: uma segunda chamada leria as curvas
        ideais como se fossem as declaradas. Ver
        :func:`~.opendss_pv.idealize_pvsystems`.
        """
        self._declared_pv_conversion = opendss_pv.idealize_pvsystems(self.dss)

    def _relax_generators(self) -> None:
        """Abre a faixa de tensão dos Generators do circuito recém-compilado.

        Mesma razão e mesma regra de :meth:`_idealize_pvsystems`: a potência
        comandada tem de ser a entregue, a troca vem antes da primeira solução,
        e uma segunda chamada na mesma compilação leria a faixa relaxada como se
        fosse a declarada. Ver :func:`~.opendss_generator.relax_voltage_band`.
        """
        self._declared_generator_band = opendss_generator.relax_voltage_band(self.dss)

    def invalidate_snapshot(self) -> None:
        """Drop cached solution results.

        Called on every solve and on every circuit edit. Any code that mutates
        the circuit outside this wrapper must call it, or reads will keep
        serving values from the superseded solution.
        """
        self._snapshot.clear()

    def run_command(self, cmd: str) -> None:
        """
        Executes a direct text command in the OpenDSS engine.

        Args:
            cmd (str): The DSS command to execute.

        O erro é detectado pelo código do motor, e não só pela palavra "error"
        no status: das mensagens de erro do OpenDSS, poucas a contêm —
        ``Unknown parameter`` (580), ``Unknown Command`` (302) e ``... not
        found`` (180) passavam como se fossem um aviso. A descrição do erro
        (``error_desc``) não é lida: no ``py-dss-interface`` 2.3.0 ela derruba o
        processo com falha de segmentação; o texto do status já a traz.

        Raises:
            OpenDSSException: If the command returns an error and fail_on_error is True.
        """
        self.invalidate_snapshot()
        status = self.dss.text(cmd)
        # O motor zera o código a cada comando e a cada leitura: lido aqui, logo
        # depois do comando, ele é deste comando, e de nenhum anterior.
        code = self.dss.errorinterface.error_code

        if code or (status and "error" in status.lower()):
            self.fail(f"Status ({cmd}): [OpenDSS {code}] {status}")
        elif status:
            self.print(f"Status ({cmd}): {status}")

    def redirect(self, filename: str) -> None:
        """
        Compiles a specific .dss file.

        Args:
            filename (str): Path to the file.
        """
        self.print(f"Running file: {filename}")
        self.invalidate_snapshot()
        base_dir = os.getcwd()
        try:
            with self._dialogs_while_compiling():
                self.dss.text(f'compile "{filename}"')
            self._after_compile()
        finally:
            os.chdir(base_dir)

    def load_buscoords(self, path: str | os.PathLike) -> bool:
        """Carrega um arquivo de coordenadas de barras no circuito compilado.

        Vários alimentadores de teste do IEEE trazem o arquivo sem carregá-lo
        no ``.dss`` mestre; sem ele as coordenadas ficam zeradas, o que só
        apareceria depois, como um desenho empilhado na origem.

        O caminho é resolvido contra o diretório de trabalho, o mesmo em que a
        existência é conferida, e chega absoluto ao motor e ao aviso.

        Um arquivo inexistente vira aviso, e não erro: as coordenadas servem ao
        desenho, e o estudo não depende delas. O **conteúdo**, o motor não
        confere — medido: um arquivo malformado ou vazio passa sem código de
        erro e não muda coordenada nenhuma. O comando segue por
        :meth:`run_command`, de modo que um erro que o motor acuse interrompe.

        Args:
            path: Caminho do arquivo de coordenadas (``barra, x, y`` por linha).

        Returns:
            ``True`` se o arquivo foi enviado ao motor; ``False`` se não existe.
        """
        path = pathlib.Path(path).resolve()

        if not path.exists():
            print(
                f"[OpenTES][AVISO] Arquivo de coordenadas '{path}' nao encontrado; "
                "as barras ficarao sem coordenadas."
            )
            return False

        self.run_command(f'Buscoords "{path}"')
        return True

    def run_dss(self, no_controls: bool = False) -> None:
        """Resolve o fluxo de potência e confere se a solução convergiu.

        Um solve que para no limite de iterações devolve tensões com a mesma
        cara das de um solve convergido, e o motor não reclama: ``converged``
        precisa ser consultado. Sem isso um passo truncado segue adiante como se
        estivesse certo, e num estudo de vários dias nada no resultado denuncia.

        A falha respeita ``fail_on_error``: por padrão interrompe, e com o erro
        desligado apenas registra. Quem precisa tolerar um passo ruim — em vez
        de perder a execução inteira — desliga o erro e acompanha o estado pelo
        modelo mosaik ``Circuit``, que expõe ``converged`` e ``iterations``.

        Args:
            no_controls: Se ``True``, usa ``solve_no_control()``.

        Raises:
            OpenDSSException: Se a solução não convergir e ``fail_on_error``
                estiver ligado.
        """
        self.invalidate_snapshot()
        try:
            if no_controls:
                self.dss.solution.solve_no_control()
            else:
                self.dss.solution.solve()

            # Em snapshot o motor resolve o fluxo mas não integra a energia das
            # baterias: é este comando que faz o SoC andar um passo. Sem bateria
            # ele não faz nada, e por isso roda sempre — a guarda que havia
            # nunca desligava, e não acompanharia uma recompilação.
            self.dss.text("UpdateStorage")

        except Exception as e:
            self.dss.text("export Eventlog")
            self.fail(f"An error occurred during DSS solution: {e}")
            return

        if not self.dss.solution.converged:
            self.fail(
                f"A solucao nao convergiu em {self.dss.solution.iterations} iteracoes "
                f"(max_iterations={self.dss.solution.max_iterations}, "
                f"tolerance={self.dss.solution.tolerance:g}). As tensoes resultantes "
                "nao resolvem o circuito; aumente max_iterations ao construir o "
                "wrapper, ou desligue fail_on_error e acompanhe `converged` pelo "
                "modelo Circuit."
            )

    def set_element(self, name: str, element: str) -> None:
        """
        Sets the active element in the DSS circuit.

        Args:
            name (str): Element name (e.g., 'load1').
            element (str): Element class (e.g., 'Load').
        """
        full_name = f"{element}.{name}"
        self.dss.circuit.set_active_element(full_name)
        if self.dss.cktelement.name.lower() != full_name.lower():
            raise OpenDSSException(f'{element} "{name}" does not exist')

    def print(self, *msg: Any) -> None:
        """Prints a message with timestamp and class name."""
        print(f"{dt.datetime.now()} - {self.name}:", *msg)

    def fail(self, *msg: Any) -> None:
        """Raises an exception or prints an error depending on fail_on_error configuration."""
        if self.fail_on_error:
            raise OpenDSSException(*msg)
        else:
            self.print(*msg)
