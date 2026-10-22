from pathlib import Path

from voice_runtime import engines


ROOT = Path(__file__).resolve().parents[1]


def test_whisper_engine_and_its_direct_dependencies_are_removed():
    assert not hasattr(engines, 'LocalWhisperEngine')
    requirements = (ROOT / 'requirements.txt').read_text()
    assert 'faster-whisper' not in requirements
    assert 'python-multipart' not in requirements


def test_deployments_do_not_configure_whisper():
    for filename in ('docker-compose.yml', 'k8s/voice-runtime.yaml'):
        assert 'WHISPER_' not in (ROOT / filename).read_text()


def test_container_uses_one_worker_for_one_resident_gpu_model():
    dockerfile = (ROOT / 'Dockerfile').read_text()
    assert '"--workers", "1"' in dockerfile


def test_single_gpu_rollout_releases_old_pod_before_starting_new_one():
    manifest = (ROOT / 'k8s/voice-runtime.yaml').read_text()
    assert 'strategy:\n    type: Recreate' in manifest
