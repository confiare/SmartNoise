import json
import os

if os.name != 'nt':
    # auto-update the protos
    import subprocess

    # protoc must be installed and on path
    package_dir = os.path.join(os.getcwd(), 'whitenoise')
    subprocess.call(f"protoc --python_out={package_dir} *.proto", shell=True, cwd=os.path.abspath('../prototypes/'))
    subprocess.call(f"sed -i -E 's/^import.*_pb2/from . &/' *.py", shell=True, cwd=package_dir)

if os.name == 'nt' and not os.path.exists('whitenoise/api_pb2.py'):
    print('make sure to run protoc to generate python proto bindings, and fix package imports to be relative to whitenoise')

components_dir = os.path.abspath("../prototypes/components")

generated_code = """
from . import Component, privacy_usage as to_privacy_usage

# Warning, this file is autogenerated by code_generation.py. Don't modify this manually.

"""

# This links the variant in the Component proto to the corresponding message
variant_message_map = {}

for file_name in os.listdir(components_dir):
    component_path = os.path.join(components_dir, file_name)
    with open(component_path, 'r') as component_schema_file:

        try:
            component_schema = json.load(component_schema_file)
        except json.JSONDecodeError as err:
            print("MALFORMED JSON FILE: ", file_name)
            raise err

    def standardize_argument(name):
        argument_schema = component_schema['arguments'][name]
        if argument_schema['type'] == 'Jagged':
            name += ', value_format="jagged"'
        return name

    def standardize_option(name):
        option_schema = component_schema['options'][name]
        if option_schema['type'] == 'repeated PrivacyUsage':
            return f'to_privacy_usage(**{name})'
        return name

    def document_argument(prefix, name, argument):
        return f'{prefix}{name}: {argument.get("description", "")}'

    docstring = f"{component_schema['id']} Component"
    if 'description' in component_schema:
        docstring += "\n\n" + component_schema['description'] + "\n"

    for argument in component_schema['arguments']:
        docstring += "\n" + document_argument(":param ", argument, component_schema['arguments'][argument])

    for option in component_schema['options']:
        docstring += "\n" + document_argument(":param ", option, component_schema['options'][option])

    docstring += "\n:param kwargs: clamp by min, max, categories, etc by passing parameters of the form [argument]_[bound]=x"

    docstring += "\n" + document_argument(":return", "", component_schema['return'])

    docstring = '\n'.join(["    " + line for line in docstring.split("\n")])

    variant_message_map[component_schema['id']] = component_schema['name']

    # remove dupes while keeping order
    signature_arguments = list(dict.fromkeys([
        *component_schema['arguments'].keys(),
        *component_schema['options'].keys(),
        '**kwargs']))

    # sort arguments with defaults to the end of the signature
    default_arguments = {
        True: [],
        False: []
    }

    # add default value to arguments
    for arg in list(dict.fromkeys([
        *component_schema['arguments'].keys(),
        *component_schema['options'].keys()])):

        if arg == '**kwargs':
            continue

        schema = component_schema['arguments'].get(arg, component_schema['options'].get(arg, {}))
        if 'default' in schema:
            default_arguments[True].append(arg + f'={schema["default"]}')
        else:
            default_arguments[False].append(arg)

    # create the function signature
    signature_string = ", ".join([*default_arguments[False], *default_arguments[True], '**kwargs'])

    # create the arguments to the Component constructor
    component_arguments = "{\n            "\
                          + ",\n            ".join([f"'{name}': Component.of({standardize_argument(name)})"
                                                  for name in component_schema['arguments']
                                                  if name != "**kwargs"]) \
                          + "\n        }"
    component_options = "{\n            " \
                        + ",\n            ".join([f"'{name}': {standardize_option(name)}"
                                                  for name in component_schema['options']
                                                  if name != "**kwargs"]) \
                        + "\n        }"
    component_constraints = "None"

    # handle components with unknown number of arguments
    if "**kwargs" in component_schema['arguments']:
        component_arguments = f"{{**kwargs, **{component_arguments}}}"
    elif "**kwargs" in component_schema['options']:
        component_options = f"{{**kwargs, **{component_options}}}"
    else:
        component_constraints = "kwargs"

    # build the call to create a Component with the prior argument strings
    generated_code += f"""
def {component_schema['name']}({signature_string}):
    \"\"\"\n{docstring}
    \"\"\"
    return Component(
        "{component_schema['id']}",
        arguments={component_arguments},
        options={component_options},
        constraints={component_constraints})

"""

output_path = os.path.join(os.getcwd(), 'whitenoise', 'components.py')
with open(output_path, 'w') as generated_file:
    generated_file.write(generated_code)

variant_message_map_path = os.path.join(os.getcwd(), 'whitenoise', 'variant_message_map.json')
with open(variant_message_map_path, 'w') as generated_map_file:
    json.dump(variant_message_map, generated_map_file, indent=4)