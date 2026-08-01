"""Reference provider implementations for Baygon.

These plugins live OUTSIDE the core on purpose: the core never imports
them. They are loaded only when ``baygon.yaml`` declares them, which is
what keeps every provider replaceable without touching the core.
"""
