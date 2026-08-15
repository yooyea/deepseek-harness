"""Shared control-plane test doubles and configuration."""

from app.config import Settings


def settings() -> Settings:
    """Return complete non-secret test configuration."""
    return Settings(
        database_url="postgresql://test",
        docker_socket="/var/run/docker.sock",
        admin_user="admin",
        admin_password="secret",
        tenant_image="example/harness:latest",
        public_host="203.0.113.10",
        tenant_scheme="http",
        port_start=18100,
        port_end=18110,
        default_cpu=1,
        default_memory_mb=1536,
        max_cpu_percent=70,
        max_load_ratio=0.9,
        minimum_free_memory_mb=2048,
        minimum_free_disk_percent=15,
        tenant_cpu_reservation_ratio=0.8,
        secret_key="test",
        runtime_base_url="http://control/api/runtime",
        oss_endpoint="https://oss.example",
        oss_region="cn-shanghai",
        oss_bucket="bucket",
        oss_access_key_id="id",
        oss_access_key_secret="secret",
    )
