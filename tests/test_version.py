import dida_v2_client.version as version_module


def test_package_version_has_source_tree_fallback(monkeypatch):
    def missing_distribution(name):
        raise version_module.PackageNotFoundError(name)

    monkeypatch.setattr(version_module, "version", missing_distribution)

    assert version_module.package_version() == "0+unknown"
