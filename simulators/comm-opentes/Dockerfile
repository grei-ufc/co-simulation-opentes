FROM omnetpp/omnetpp:u22.04-6.0

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    libzmq5-dev \
    git \
    cmake \
    build-essential \
    nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/zeromq/cppzmq.git /tmp/cppzmq \
    && cd /tmp/cppzmq \
    && mkdir build \
    && cd build \
    && cmake .. \
    && make install \
    && rm -rf /tmp/cppzmq

WORKDIR /root/models
COPY . /root/models/

EXPOSE 5555/tcp

CMD ["bash", "-lc", "source /root/omnetpp/setenv && opp_makemake -f --deep -O out -o sim_exec -lzmq && make && ./sim_exec -u Cmdenv -c General"]
