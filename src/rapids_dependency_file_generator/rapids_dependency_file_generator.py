import itertools
import os
from collections import defaultdict

import yaml

from .constants import (
    OutputTypes,
    cli_name,
    default_channels,
    default_conda_dir,
    default_requirements_dir,
)

OUTPUT_ENUM_VALUES = [str(x) for x in OutputTypes]
NON_NONE_OUTPUT_ENUM_VALUES = [str(x) for x in OutputTypes if not x == OutputTypes.NONE]


def dedupe(dependencies):
    deduped = [dep for dep in dependencies if not isinstance(dep, dict)]
    deduped = sorted(list(set(deduped)))
    dict_like_deps = [dep for dep in dependencies if isinstance(dep, dict)]
    dict_deps = defaultdict(list)
    for dep in dict_like_deps:
        for key, values in dep.items():
            dict_deps[key].extend(values)
            dict_deps[key] = sorted(list(set(dict_deps[key])))
    if dict(dict_deps):
        deduped.append(dict(dict_deps))
    return deduped


def grid(gridspec):
    """Yields the Cartesian product of a `dict` of iterables.

    The input ``gridspec`` is a dictionary whose keys correspond to
    parameter names. Each key is associated with an iterable of the
    values that parameter could take on. The result is a sequence of
    dictionaries where each dictionary has one of the unique combinations
    of the parameter values.
    """
    for values in itertools.product(*gridspec.values()):
        yield dict(zip(gridspec.keys(), values))


def make_dependency_file(
    file_type, name, config_file, output_path, conda_channels, dependencies
):
    relative_path_to_config_file = os.path.relpath(config_file, output_path)
    file_contents = f"""\
# This file is generated by `{cli_name}`.
# To make changes, edit {relative_path_to_config_file} and run `{cli_name}`.
"""
    if file_type == str(OutputTypes.CONDA):
        file_contents += yaml.dump(
            {
                "name": os.path.splitext(name)[0],
                "channels": conda_channels,
                "dependencies": dependencies,
            }
        )
    if file_type == str(OutputTypes.REQUIREMENTS):
        file_contents += "\n".join(dependencies) + "\n"
    return file_contents


def ensure_list(item):
    return item if isinstance(item, list) else [item]


def get_file_output(output):
    output = ensure_list(output)

    if output == [str(OutputTypes.NONE)]:
        return []

    if len(output) > 1 and str(OutputTypes.NONE) in output:
        raise ValueError("'output: [none]' cannot be combined with any other values.")

    for value in output:
        if value not in NON_NONE_OUTPUT_ENUM_VALUES:
            raise ValueError(
                "'output' key can only be "
                + ", ".join(f"'{x}'" for x in OUTPUT_ENUM_VALUES)
                + f" or a list of the non-'{OutputTypes.NONE}' values."
            )
    return output


def get_entry_output_types(output_types):
    output_types = ensure_list(output_types)
    for value in output_types:
        if value not in NON_NONE_OUTPUT_ENUM_VALUES:
            raise ValueError(
                "'output_types' key can only be "
                + ", ".join(f"'{x}'" for x in NON_NONE_OUTPUT_ENUM_VALUES)
                + " or a list of these values."
            )
    return output_types


def get_filename(file_type, file_prefix, matrix_combo):
    file_type_prefix = ""
    file_ext = ""
    if file_type == str(OutputTypes.CONDA):
        file_ext = ".yaml"
    if file_type == str(OutputTypes.REQUIREMENTS):
        file_ext = ".txt"
        file_type_prefix = "requirements"
    suffix = "_".join([f"{k}-{v}" for k, v in matrix_combo.items()])
    filename = "_".join(
        x for x in [file_type_prefix, file_prefix, suffix] if x
    ).replace(".", "")
    return filename + file_ext


def get_output_path(file_type, config_file_path, file_config):
    output_path = "."
    if file_type == str(OutputTypes.CONDA):
        output_path = file_config.get("conda_dir", default_conda_dir)
    if file_type == str(OutputTypes.REQUIREMENTS):
        output_path = file_config.get("requirements_dir", default_requirements_dir)
    return os.path.join(os.path.dirname(config_file_path), output_path)


def should_use_specific_entry(matrix_combo, specific_entry_matrix):
    if not specific_entry_matrix:
        return True

    for specific_key, specific_value in specific_entry_matrix.items():
        if matrix_combo.get(specific_key) != specific_value:
            return False
    return True


def make_dependency_files(parsed_config, config_file_path, to_stdout):

    channels = parsed_config.get("channels", default_channels) or default_channels
    files = parsed_config["files"]
    for file_name, file_config in files.items():
        includes = file_config["includes"]
        file_types_to_generate = get_file_output(file_config["output"])

        for file_type in file_types_to_generate:
            for matrix_combo in grid(file_config.get("matrix", {})):
                dependencies = []

                for include in includes:
                    dependency_entry = parsed_config["dependencies"][include]
                    common_entries = dependency_entry.get("common", [])
                    specific_entries = dependency_entry.get("specific", [])

                    for common_entry in common_entries:
                        if file_type not in common_entry["output_types"]:
                            continue
                        dependencies.extend(common_entry["packages"])

                    for specific_entry in specific_entries:
                        if file_type not in specific_entry["output_types"]:
                            continue
                        specific_matrices = specific_entry["matrices"]

                        for specific_matrices_entry in specific_matrices:
                            if should_use_specific_entry(
                                matrix_combo, specific_matrices_entry["matrix"]
                            ):
                                dependencies.extend(
                                    specific_matrices_entry["packages"] or []
                                )
                                break
                        else:
                            raise ValueError(
                                f"No matching matrix found in '{include}' for: {matrix_combo}"
                            )

                # Dedupe deps and print / write to filesystem
                full_file_name = get_filename(file_type, file_name, matrix_combo)
                deduped_deps = dedupe(dependencies)

                def make_dependency_file_factory(output_path):
                    return make_dependency_file(
                        file_type,
                        full_file_name,
                        config_file_path,
                        output_path,
                        channels,
                        deduped_deps,
                    )

                if to_stdout:
                    output_path = "."
                    contents = make_dependency_file_factory(output_path)
                    print(contents)
                else:
                    output_path = get_output_path(
                        file_type, config_file_path, file_config
                    )
                    contents = make_dependency_file_factory(output_path)
                    os.makedirs(output_path, exist_ok=True)
                    with open(
                        os.path.join(output_path, full_file_name),
                        "w",
                    ) as f:
                        f.write(contents)
