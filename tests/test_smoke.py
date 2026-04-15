def test_imports() -> None:
    import hyperloop
    import hyperloop.adapters
    import hyperloop.domain
    import hyperloop.ports

    # Reference the imports so pyright doesn't flag them as unused
    assert hyperloop is not None
    assert hyperloop.adapters is not None
    assert hyperloop.domain is not None
    assert hyperloop.ports is not None
