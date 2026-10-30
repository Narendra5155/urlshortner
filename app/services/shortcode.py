import secrets
import string

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 7

# Paths that would shadow app routes if used as short codes.
RESERVED = {"api", "docs", "redoc", "openapi.json", "favicon.ico", "health"}


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
