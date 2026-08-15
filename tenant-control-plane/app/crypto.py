"""Encryption helpers for credentials that must survive container replacement."""

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    """Encrypt and decrypt tenant secrets with the deployment key."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (TypeError, ValueError) as error:
            raise RuntimeError("CONTROL_PLANE_SECRET_KEY must be a Fernet key") from error

    def encrypt(self, value: str) -> str:
        """Encrypt a UTF-8 secret for PostgreSQL storage."""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """Decrypt a stored secret or fail before provisioning a replacement."""
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as error:
            raise RuntimeError("stored tenant secret cannot be decrypted") from error
