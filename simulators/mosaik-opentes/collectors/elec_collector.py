"""
A simple data collector that saves all input into a csv file.

"""
import collections
import pandas as pd

import mosaik_api

from pathlib import Path

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent

META = {
    'type': 'event-based',
    'models': {
        'Monitor': {
            'public': True,
            'any_inputs': True,
            'params': [],
            'attrs': [],
        },
    },
}


class Collector(mosaik_api.Simulator):
    def __init__(self):
        super().__init__(META)
        self.eid = None
        self.data = collections.defaultdict(lambda:
                                            collections.defaultdict(dict))
        self.print_results = False
        self.data = collections.defaultdict(lambda: collections.defaultdict(dict))

    def init(self, sid, time_resolution, start_date,
             date_format='%Y-%m-%d %H:%M:%S', output_file= parent_dir / 'output' / 'results.csv',
             print_results=False):
        self.time_resolution = time_resolution
        self.start_date = pd.to_datetime(start_date, format=date_format)
        self.output_file = output_file
        self.print_results = print_results
        return self.meta

    def create(self, num, model):
        if num > 1 or self.eid is not None:
            raise RuntimeError('Can only create one instance of Monitor.')

        self.eid = 'Monitor'

        return [{'eid': self.eid, 'type': model}]

    def step(self, time, inputs, max_advance):
        # print(inputs)
        current_date = (self.start_date
                        + pd.Timedelta(time * self.time_resolution, unit='seconds'))

        df_dict = {'date': current_date}

        data = inputs.get(self.eid, {})
        for attr, values in data.items():
            for src, value in values.items():
                self.data[src][attr][time] = value
                df_dict[f'{src}-{attr}'] = [value]

        df = pd.DataFrame.from_dict(df_dict)
        df = df.set_index('date')
        if time == 0:
            df.to_csv(self.output_file, mode='w', header=True)
        else:
            df.to_csv(self.output_file, mode='a', header=False)

        return None

    def finalize(self):
        if self.print_results:
            #print('Collected data:')
            for sim, sim_data in sorted(self.data.items()):
                print('- %s:' % sim)
                for attr, values in sorted(sim_data.items()):
                    print('  - %s: %s' % (attr, values))


if __name__ == '__main__':
    mosaik_api.start_simulation(Collector())
