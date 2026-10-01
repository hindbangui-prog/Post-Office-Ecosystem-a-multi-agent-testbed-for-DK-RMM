"""
The CrewAI side of the prototype: the one Ollama-backed LLM, the transport audit
that attributes every model call, and the check that the configured model is the
one installed. Import the submodules directly; this package imports nothing so
that `crew.identity` can be used without loading CrewAI.
"""
