import toml # pyright: ignore[reportMissingModuleSource]

def read_pipfile(path="pipenv/Pipfile"):
    with open(path, "r", encoding="utf-8") as f:
        return toml.load(f)

def exclude(package_name, exclude_versions, pipfile_path="pipenv/Pipfile"):
    pipfile = read_pipfile(pipfile_path)
    packages = pipfile.get("packages", {})

    if package_name in packages:
        # Eğer paket dict ise (örneğin {version="*", index="pypi"})
        if isinstance(packages[package_name], dict):
            packages[package_name]["exclude_versions"] = exclude_versions
        else:
            # string formatta ise örn: "==1.0"
            packages[package_name] = {
                "version": packages[package_name],
                "exclude_versions": exclude_versions
            }
    else:
        # Paket yoksa yeni ekle
        packages[package_name] = {
            "version": "*",
            "exclude_versions": exclude_versions
        }

    pipfile["packages"] = packages

    # Pipfile'ı TOML olarak tekrar yaz
    with open(pipfile_path, "w", encoding="utf-8") as f:
        toml.dump(pipfile, f)

# Example kullanım:
# exclude("tracerite", ["1.1.2"])
