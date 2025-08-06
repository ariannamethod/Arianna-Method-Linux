from letsgo import register_command


def greet(_: str) -> str:
    return "Hello from plugin"


register_command("/greet", greet)
