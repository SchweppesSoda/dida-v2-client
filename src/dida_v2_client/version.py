from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("dida-v2-client")
    except PackageNotFoundError:
        return "0+unknown"


USER_AGENT = f"dida-v2-client/{package_version()}"
