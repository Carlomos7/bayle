//! The gateway between the web view and the Python engine (docs/decisions/0015-rust-gateway.md): it starts and
//! supervises the engine, holds its port and token, forwards only allowlisted operations with a URL it builds itself,
//! and relays the engine's events in order. It holds no Bayle logic.

mod contract;
mod engine;
mod error;
mod gateway;

pub use contract::{CONTRACT_MAJOR, OPERATIONS, Operation, build_url, operation};
pub use engine::{EngineCommand, Handshake};
pub use error::GatewayError;
pub use gateway::{EngineState, Gateway, GatewayEvent, Status};
