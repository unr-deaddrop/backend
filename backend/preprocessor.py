"""
The "magic" preprocessor system.
The preprocessor accepts a JSON schema (as a Python dict) and recursively searches 
for keys of the format `_preprocess_<key>`, where `<key>` is some keyword
denoting an action to take. The value of that key determines the "argument"
used for preprocessing.
For example, the JSON schema generated by Pygin doesn't specify a default
agent ID, because the server is expected to generate this itself. Pygin's agent
configuration JSON schema looks like this:
```py
{
  "description": "Agent-wide configuration definitions. Includes both non-sensitive and\nsensitive configurations set at runtime.\nSee agent.cfg for more details.",
  "properties": {
    "AGENT_ID": {
      "_preprocess_form_default": True,
      "description": "The agent's UUID.",
      "format": "uuid",
      "title": "Agent Id",
      "type": "string"
    }
  }
}
```
When the preprocessor sees `"_preprocess_create_id": true`, it deletes
this key and sets a random AGENT_ID as the default. This can then be used as
the default value on the form, effectively generating a random agent ID. 
Additionally, the form field is set read-only, effectively preventing the user
from accidentally changing the field.
The following would then be sent as the schema to the frontend:
```json
{
  "description": "Agent-wide configuration definitions. Includes both non-sensitive and\nsensitive configurations set at runtime.\nSee agent.cfg for more details.",
  "properties": {
    "AGENT_ID": {
      "default": "AGENT_ID",
      "readonly": true,
      "description": "The agent's UUID.",
      "format": "uuid",
      "title": "Agent Id",
      "type": "string"
    }
}
```
Multiple actions can be included, though generally not recommended. Preprocessor 
keys are evaluated in the order they appear from Python's key iteration.
When an action does not require an argument, such as create_id, it is only required
that the preprocessor key exists; any value is acceptable for the preprocessor value,
such as `true`.
Various other actions are provided. A full list of available actions are below:
- create_id(): Substitute with a random UUIDv4, set as default, and make read-only.
- settings_val(val): Substitute with a value defined in Django's settings,
    set as default, and make read-only.
"""

from typing import Any
import re
import uuid

from django.conf import settings

def preprocess_dict(input: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively process a dictionary.
    """
    # The iterator is converted to a tuple so we don't run into the issue of the
    # dictionary changing size as we pop off keys.
    for key, value in tuple(input.items()):
        if isinstance(value, dict):
            preprocess_dict(value)

        if match := re.match(r'_preprocess_(.*)', key):
            # Remove the preprocessor key
            input.pop(key)
            # Perform the action
            action = match.group(1)
            preprocess_router(input, action, value)
            
    return input

def preprocess_create_id(input: dict[str, Any], _value: Any) -> None:
    """
    Insert a random UUIDv4, set it as the default for that field, and make it
    read-only.
    
    The value is ignored.
    """
    # Unfortunately, this isn't Pydantic and json/json5 won't auto-serialize
    # UUID objects
    input['default'] = str(uuid.uuid4())
    input['readonly'] = True

def preprocess_settings_val(input: dict[str, Any], value: Any) -> None:
    """
    Substitute with a value defined in Django's settings, set as default, and 
    make read-only.
    """
    input['default'] = getattr(settings, value)
    input['readonly'] = True


ACTIONS = {
    'create_id': preprocess_create_id,
    'settings_val': preprocess_settings_val,
}

def preprocess_router(input: dict[str, Any], action: str, value: Any) -> None:
    """
    Apply the specified preprocessor action to the dictionary.
    
    All operations are expected to be in-place.
    """
    if action not in ACTIONS:
        raise RuntimeError(f"Preprocessor action {action} not recognized")

    preprocess_func = ACTIONS[action]
    preprocess_func(input, value)

if __name__ == "__main__":
    test_d = {
        "description": "Agent-wide configuration definitions. Includes both non-sensitive and\nsensitive configurations set at runtime.\nSee agent.cfg for more details.",
        "properties": {
            "AGENT_ID": {
            "_preprocess_create_id": True,
            "description": "The agent's UUID.",
            "format": "uuid",
            "title": "Agent Id",
            "type": "string"
            }
        }
    }

    print(preprocess_dict(test_d))