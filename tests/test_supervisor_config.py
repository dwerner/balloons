"""Tests for supervisor_config module."""

import tempfile
from pathlib import Path

import pytest

from supervisor_config import (
    HostConfig,
    SupervisorConfig,
)


class TestHostConfig:
    """Tests for HostConfig."""

    def test_local_host(self):
        """Local host requires no additional fields."""
        host = HostConfig(name="local", type="local")
        host.validate()  # Should not raise
        assert host.type == "local"

    def test_ssh_host_requires_fields(self):
        """SSH host requires host and user."""
        host = HostConfig(name="server", type="ssh")
        with pytest.raises(ValueError, match="requires 'host' field"):
            host.validate()

        host = HostConfig(name="server", type="ssh", host="192.168.0.1")
        with pytest.raises(ValueError, match="requires 'user' field"):
            host.validate()

        host = HostConfig(
            name="server", type="ssh", host="192.168.0.1", user="dan"
        )
        host.validate()  # Should not raise

    def test_ssh_target(self):
        """SSH target string is user@host."""
        host = HostConfig(
            name="server", type="ssh", host="192.168.0.1", user="dan"
        )
        assert host.ssh_target() == "dan@192.168.0.1"

    def test_ssh_args_default_port(self):
        """SSH args without custom port."""
        host = HostConfig(
            name="server", type="ssh", host="192.168.0.1", user="dan"
        )
        assert host.ssh_args() == ["dan@192.168.0.1"]

    def test_ssh_args_custom_port(self):
        """SSH args with custom port."""
        host = HostConfig(
            name="server", type="ssh", host="192.168.0.1", user="dan", port=2222
        )
        assert host.ssh_args() == ["-p", "2222", "dan@192.168.0.1"]

    def test_tags(self):
        """Host can have tags."""
        host = HostConfig(
            name="gpu", type="ssh", host="192.168.0.1", user="dan",
            tags=["amd", "ml", "docker"]
        )
        assert "amd" in host.tags
        assert "ml" in host.tags


class TestSupervisorConfig:
    """Tests for SupervisorConfig."""

    def test_default_config_has_local(self):
        """Default config includes local host."""
        config = SupervisorConfig()
        assert "local" not in config.hosts  # Empty by default

        # But load() should add local
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "supervisor.yaml"
            config = SupervisorConfig.load(path)
            assert "local" in config.hosts
            assert config.hosts["local"].type == "local"

    def test_load_from_yaml(self):
        """Load config from YAML file."""
        yaml_content = """
hosts:
  local:
    type: local
    tags: [docker]
  gpu-box:
    type: ssh
    host: 192.168.0.196
    user: dan
    tags: [amd, ml]

backend_hosts:
  llama-nvidia: gpu-box
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "supervisor.yaml"
            path.write_text(yaml_content)

            config = SupervisorConfig.load(path)

            assert "local" in config.hosts
            assert "gpu-box" in config.hosts
            assert config.hosts["gpu-box"].host == "192.168.0.196"
            assert config.hosts["gpu-box"].user == "dan"
            assert "amd" in config.hosts["gpu-box"].tags
            assert config.backend_hosts["llama-nvidia"] == "gpu-box"

    def test_query_hosts_by_tags(self):
        """Query hosts by tags."""
        config = SupervisorConfig(
            hosts={
                "local": HostConfig(name="local", type="local", tags=["docker"]),
                "gpu": HostConfig(
                    name="gpu", type="ssh", host="192.168.0.1", user="dan",
                    tags=["docker", "ml"]
                ),
                "web": HostConfig(
                    name="web", type="ssh", host="192.168.0.2", user="deploy",
                    tags=["nginx", "docker"]
                ),
            }
        )

        # All hosts with docker
        results = config.query_hosts(tags=["docker"])
        assert len(results) == 3

        # Hosts with both docker and ml
        results = config.query_hosts(tags=["docker", "ml"])
        assert len(results) == 1
        assert results[0].name == "gpu"

    def test_query_hosts_by_type(self):
        """Query hosts by type."""
        config = SupervisorConfig(
            hosts={
                "local": HostConfig(name="local", type="local"),
                "gpu": HostConfig(
                    name="gpu", type="ssh", host="192.168.0.1", user="dan"
                ),
            }
        )

        results = config.query_hosts(host_type="ssh")
        assert len(results) == 1
        assert results[0].name == "gpu"

        results = config.query_hosts(host_type="local")
        assert len(results) == 1
        assert results[0].name == "local"

    def test_get_host_for_backend(self):
        """Get host for a backend."""
        config = SupervisorConfig(
            hosts={
                "local": HostConfig(name="local", type="local"),
                "gpu": HostConfig(
                    name="gpu", type="ssh", host="192.168.0.1", user="dan"
                ),
            },
            backend_hosts={"llama-nvidia": "gpu"},
        )

        host = config.get_host_for_backend("llama-nvidia")
        assert host is not None
        assert host.name == "gpu"

        host = config.get_host_for_backend("unknown")
        assert host is None

    def test_to_dict_and_save(self):
        """Config can be serialized and saved."""
        config = SupervisorConfig(
            hosts={
                "local": HostConfig(name="local", type="local", tags=["docker"]),
                "gpu": HostConfig(
                    name="gpu", type="ssh", host="192.168.0.1", user="dan",
                    port=2222, tags=["ml"], description="GPU server"
                ),
            },
            backend_hosts={"llama": "gpu"},
        )

        data = config.to_dict()
        assert "hosts" in data
        assert "backend_hosts" in data
        assert data["hosts"]["gpu"]["port"] == 2222
        assert data["hosts"]["gpu"]["tags"] == ["ml"]

        # Save and reload
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "supervisor.yaml"
            config._config_path = path
            config.save()

            reloaded = SupervisorConfig.load(path)
            assert "gpu" in reloaded.hosts
            assert reloaded.hosts["gpu"].port == 2222
