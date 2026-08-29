# Third-party notices

JaegerAI's runner adapter is designed to interoperate with a separately
installed Hermes WebUI, copyright 2025 Hermes Web UI Contributors, licensed
under the MIT License. The full license text is available in the upstream
project: https://github.com/nesquena/hermes-webui/blob/main/LICENSE

No Hermes WebUI frontend source is copied into JaegerAI. JaegerAI does not
include, import, or execute Hermes Agent. Hermes WebUI communicates with this
adapter over its `runner-local` contract; the adapter communicates only with
JaegerAI's versioned bridge protocol.
