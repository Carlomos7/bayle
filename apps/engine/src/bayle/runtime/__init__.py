"""The runtime: the one place the program is put together. bootstrap.create_engine builds the engine and binds its
slots; bootstrap.bind_ports binds the features' ports to the adapters; features composes every feature's typed
interface once; startup and startup_recovery are the start-up steps; instance keeps one window per data folder."""
