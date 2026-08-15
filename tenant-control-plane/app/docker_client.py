"""Restricted Docker Engine client over the local Unix socket."""

from __future__ import annotations

import http.client
import json
import socket
from typing import Any
from urllib.parse import quote, urlencode

MANAGED_LABEL = "com.deepharness.tenant-managed"
TENANT_LABEL = "com.deepharness.tenant-slug"


class DockerError(RuntimeError):
    """Docker Engine returned an unexpected response."""


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP connection transported through a Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        """Connect to the configured Unix socket."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


class DockerClient:
    """Docker operations limited to DeepHarness-labelled resources."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        connection = UnixHTTPConnection(self.socket_path)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            content = response.read()
        except OSError as error:
            raise DockerError(f"cannot reach Docker Engine: {error}") from error
        finally:
            connection.close()
        if response.status not in expected:
            message = content.decode(errors="replace")
            try:
                message = json.loads(message).get("message", message)
            except json.JSONDecodeError:
                pass
            raise DockerError(f"Docker {method} {path} returned {response.status}: {message}")
        if not content:
            return None
        decoded = content.decode(errors="replace")
        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            return decoded

    def ping(self) -> bool:
        """Return whether Docker Engine responds."""
        try:
            return self._request("GET", "/_ping", expected=(200,)) == "OK"
        except DockerError:
            return False

    def info(self) -> dict[str, Any]:
        """Return Docker host information."""
        return self._request("GET", "/info")

    def image_exists(self, image: str) -> bool:
        """Return whether the approved tenant image exists locally."""
        try:
            self._request("GET", f"/images/{quote(image, safe='')}/json")
            return True
        except DockerError as error:
            if "returned 404" in str(error):
                return False
            raise

    def create_container(
        self,
        *,
        name: str,
        slug: str,
        image: str,
        host_port: int,
        access_username: str,
        access_password: str,
        trusted_host: str,
        cpu_limit: float,
        memory_mb: int,
        runtime_url: str,
        runtime_token: str,
        safe_mode: bool = False,
    ) -> str:
        """Create a resource-limited Harness container."""
        query = urlencode({"name": name})
        result = self._request(
            "POST",
            f"/containers/create?{query}",
            {
                "Image": image,
                "Env": [
                    f"DSH_ACCESS_USER={access_username}",
                    f"DSH_ACCESS_PASSWORD={access_password}",
                    f"DSH_TRUSTED_HOST={trusted_host}",
                    f"DEEPHARNESS_CONTROL_PLANE_URL={runtime_url}",
                    f"DEEPHARNESS_TENANT_TOKEN={runtime_token}",
                    f"DSH_PLUGIN_SAFE_MODE={'1' if safe_mode else '0'}",
                ],
                "Labels": {MANAGED_LABEL: "true", TENANT_LABEL: slug},
                "ExposedPorts": {"8080/tcp": {}},
                "HostConfig": {
                    "Tmpfs": {"/data": f"rw,exec,nosuid,nodev,size={max(memory_mb // 2, 256)}m"},
                    "ExtraHosts": ["host.docker.internal:host-gateway"],
                    "PortBindings": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(host_port)}]},
                    "RestartPolicy": {"Name": "unless-stopped"},
                    "Memory": memory_mb * 1024 * 1024,
                    "NanoCpus": int(cpu_limit * 1_000_000_000),
                    "SecurityOpt": ["no-new-privileges:true"],
                },
            },
            expected=(201,),
        )
        return str(result["Id"])

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        """Inspect one container."""
        return self._request("GET", f"/containers/{quote(container_id, safe='')}/json")

    def _assert_managed(self, container_id: str) -> None:
        inspection = self.inspect_container(container_id)
        labels = inspection.get("Config", {}).get("Labels", {})
        if labels.get(MANAGED_LABEL) != "true":
            raise DockerError("refusing to operate on a container not managed by the control plane")

    def start_container(self, container_id: str) -> None:
        """Start a managed tenant container."""
        self._assert_managed(container_id)
        self._request("POST", f"/containers/{quote(container_id, safe='')}/start", expected=(204, 304))

    def stop_container(self, container_id: str) -> None:
        """Stop a managed tenant container."""
        self._assert_managed(container_id)
        self._request("POST", f"/containers/{quote(container_id, safe='')}/stop?t=20", expected=(204, 304))

    def restart_container(self, container_id: str) -> None:
        """Restart a managed tenant container."""
        self._assert_managed(container_id)
        self._request("POST", f"/containers/{quote(container_id, safe='')}/restart?t=20", expected=(204,))

    def remove_container(self, container_id: str) -> None:
        """Force-remove a managed container while preserving its volume."""
        self._assert_managed(container_id)
        self._request("DELETE", f"/containers/{quote(container_id, safe='')}?force=true&v=false", expected=(204,))

    def container_stats(self, container_id: str) -> dict[str, Any]:
        """Return one non-streaming container resource sample."""
        return self._request("GET", f"/containers/{quote(container_id, safe='')}/stats?stream=false")
