use serde::Serialize;
use serde_json::{Value, json};

/// What a failed call returns to the web view: the engine's `Problem` body (`code`, `message`, `details`) with its HTTP
/// status, or the gateway's own error in the same shape with a `gateway.*` code.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct GatewayError {
    pub status: u16,
    pub code: String,
    pub message: String,
    pub details: Value,
}

impl GatewayError {
    pub fn gateway(status: u16, code: &str, message: impl Into<String>, details: Value) -> Self {
        Self {
            status,
            code: format!("gateway.{code}"),
            message: message.into(),
            details,
        }
    }

    pub fn not_allowed(operation: &str) -> Self {
        Self::gateway(
            403,
            "not_allowed",
            "This operation is not available here.",
            json!({ "operation": operation }),
        )
    }

    pub fn bad_parameter(name: &str, why: &str) -> Self {
        Self::gateway(
            400,
            "bad_parameter",
            format!("Parameter {name}: {why}."),
            json!({ "parameter": name }),
        )
    }

    pub fn engine_unavailable(message: impl Into<String>) -> Self {
        Self::gateway(503, "engine_unavailable", message, Value::Null)
    }

    /// An engine answer that is not a success. Its body is the engine's `Problem` when it parses as one.
    pub fn from_engine(status: u16, body: &[u8]) -> Self {
        let parsed: Value = serde_json::from_slice(body).unwrap_or(Value::Null);
        match (
            parsed.get("code").and_then(Value::as_str),
            parsed.get("message").and_then(Value::as_str),
        ) {
            (Some(code), Some(message)) => Self {
                status,
                code: code.into(),
                message: message.into(),
                details: parsed.get("details").cloned().unwrap_or(Value::Null),
            },
            // FastAPI's own answers (401, 404, 422) carry `detail` instead
            _ => Self {
                status,
                code: format!("http_{status}"),
                message: parsed
                    .get("detail")
                    .map(|d| d.to_string())
                    .unwrap_or_else(|| format!("HTTP {status}")),
                details: parsed,
            },
        }
    }
}

impl std::fmt::Display for GatewayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} ({}): {}", self.code, self.status, self.message)
    }
}

impl std::error::Error for GatewayError {}
