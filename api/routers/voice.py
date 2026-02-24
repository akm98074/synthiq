"""
Voice calibration endpoints.
"""
from __future__ import annotations

import logging

import anthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from database import get_db
from models.database import User, VoiceProfile
from models.schemas import VoiceProfileOut
from pipeline.parsers import parse_docx, parse_pdf, parse_text
from pipeline.voice_extractor import (
    extract_style_signature,
    generate_voice_system_prompt,
    merge_signatures,
)

router = APIRouter(prefix="/voice", tags=["voice"])
log = logging.getLogger(__name__)

_MAX_SAMPLES = 5


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _detect_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    return "text"


def _pages_to_text(pages: list) -> str:
    return "\n\n".join(p.text for p in pages if p.text)


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=VoiceProfileOut | None)
async def get_voice_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return None
    return VoiceProfileOut(
        id=profile.id,
        sample_count=profile.sample_count,
        style_signature=profile.style_signature,
        voice_system_prompt=profile.voice_system_prompt,
        updated_at=profile.updated_at,
    )


@router.post("/samples", response_model=VoiceProfileOut)
async def upload_voice_sample(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a writing sample (PDF, DOCX, or TXT).
    Parses the document, extracts a style signature via Claude Sonnet 4.6,
    merges it into the user's voice profile, and re-generates the system prompt.
    """
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile and profile.sample_count >= _MAX_SAMPLES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {_MAX_SAMPLES} samples already uploaded. "
                   "Delete your profile to start over.",
        )

    # Parse document to plain text
    doc_type = _detect_type(file.filename or "")
    try:
        if doc_type == "pdf":
            pages = parse_pdf(content)
        elif doc_type == "docx":
            pages = parse_docx(content)
        else:
            pages = parse_text(content)
    except Exception as exc:
        log.warning("Failed to parse voice sample %r: %s", file.filename, exc)
        raise HTTPException(
            status_code=400,
            detail="Could not parse file. Try PDF, DOCX, or TXT.",
        )

    text = _pages_to_text(pages)
    if not text.strip():
        raise HTTPException(
            status_code=400, detail="No text could be extracted from file."
        )

    # Extract style signature via Claude Sonnet 4.6
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    new_sig = await extract_style_signature(client, text)

    # Merge with existing signature (running average for numerics, last-wins for categoricals)
    existing_count = profile.sample_count if profile else 0
    existing_sig = profile.style_signature if profile else None
    merged_sig = merge_signatures(existing_sig, new_sig, existing_count)

    # Generate system prompt from merged signature
    system_prompt = generate_voice_system_prompt(merged_sig)

    # Upsert voice profile
    if profile is None:
        profile = VoiceProfile(
            user_id=current_user.id,
            sample_count=1,
            style_signature=merged_sig,
            voice_system_prompt=system_prompt,
        )
        db.add(profile)
    else:
        profile.sample_count += 1
        profile.style_signature = merged_sig
        profile.voice_system_prompt = system_prompt

    await db.flush()
    await db.refresh(profile)

    log.info(
        "Voice sample uploaded: user=%s samples=%d", current_user.id, profile.sample_count
    )
    return VoiceProfileOut(
        id=profile.id,
        sample_count=profile.sample_count,
        style_signature=profile.style_signature,
        voice_system_prompt=profile.voice_system_prompt,
        updated_at=profile.updated_at,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        await db.delete(profile)
        await db.commit()
