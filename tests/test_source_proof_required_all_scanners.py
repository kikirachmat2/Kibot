from __future__ import annotations

from Core.Scanner.source_proof import SourceProof


def test_source_proof_validate_happy_path():
    proof = SourceProof.create(
        source_type="REAL_API",
        source_name="Example",
        source_url_or_endpoint="https://example.com",
        raw_id="abc",
        symbol="ABC",
        address_or_mint="abc123",
        chain="solana",
    )
    assert SourceProof.validate(proof)


def test_source_proof_rejects_invalid_placeholder():
    proof = SourceProof.create(
        source_type="REAL_API",
        source_name="Example",
        source_url_or_endpoint="https://example.com",
        raw_id="abc",
        symbol="ABC",
        address_or_mint="fake_placeholder",
        chain="solana",
    )
    assert not SourceProof.validate(proof)
