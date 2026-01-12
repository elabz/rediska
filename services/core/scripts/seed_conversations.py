#!/usr/bin/env python3
"""Seed script to create test conversations and messages.

Run this inside the container:
    docker exec rediska-core python /app/scripts/seed_conversations.py
"""

import random
from datetime import datetime, timedelta

from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
)

# Fake Reddit usernames for testing
FAKE_USERS = [
    {"username": "TechEnthusiast42", "user_id": "t2_abc123"},
    {"username": "DataScienceNinja", "user_id": "t2_def456"},
    {"username": "CryptoWatcher2024", "user_id": "t2_ghi789"},
    {"username": "StartupFounderX", "user_id": "t2_jkl012"},
    {"username": "MLResearcher99", "user_id": "t2_mno345"},
]

# Sample conversation messages
CONVERSATIONS = [
    {
        "username": "TechEnthusiast42",
        "messages": [
            {"direction": "in", "text": "Hey, saw your post about the AI tool you're building. Looks interesting!"},
            {"direction": "out", "text": "Thanks! Yes, it's been a fun project. What aspect caught your attention?"},
            {"direction": "in", "text": "The local-first approach. I'm tired of everything being cloud-only. Privacy matters."},
            {"direction": "out", "text": "Exactly my thinking. All your data stays on your machine. No cloud sync unless you explicitly want it."},
            {"direction": "in", "text": "That's perfect. Is there a beta I can try?"},
        ],
    },
    {
        "username": "DataScienceNinja",
        "messages": [
            {"direction": "in", "text": "Quick question - does your tool support importing existing chat history?"},
            {"direction": "out", "text": "Yes! You can sync from Reddit DMs and eventually we'll add more providers."},
            {"direction": "in", "text": "Nice. I have thousands of messages I'd love to analyze with LLMs."},
        ],
    },
    {
        "username": "CryptoWatcher2024",
        "messages": [
            {"direction": "in", "text": "Yo, is this open source?"},
            {"direction": "out", "text": "Planning to open source portions of it once it's more stable."},
            {"direction": "in", "text": "Cool. Let me know when, happy to contribute."},
            {"direction": "out", "text": "Will do! What's your background? Python? TypeScript?"},
            {"direction": "in", "text": "Both actually. Full stack with a focus on backend systems."},
            {"direction": "out", "text": "Perfect. The backend is FastAPI/Python and frontend is Next.js/TypeScript."},
        ],
    },
    {
        "username": "StartupFounderX",
        "messages": [
            {"direction": "in", "text": "Hi, I run a small AI startup and we're looking for tools like this for internal use."},
            {"direction": "out", "text": "Happy to chat more about it. What's your use case?"},
            {"direction": "in", "text": "We need to manage customer conversations across multiple platforms with AI assistance."},
            {"direction": "out", "text": "That's exactly what this is designed for. Currently supporting Reddit but architecture is multi-provider."},
        ],
    },
    {
        "username": "MLResearcher99",
        "messages": [
            {"direction": "in", "text": "What LLM are you using for the AI features?"},
            {"direction": "out", "text": "Flexible - supports any OpenAI-compatible API. Local models via ollama work great."},
            {"direction": "in", "text": "Interesting. Have you tested with llama3?"},
            {"direction": "out", "text": "Yes, works well for most tasks. For complex reasoning I still prefer Claude."},
            {"direction": "in", "text": "Makes sense. The new llama models are impressive though."},
            {"direction": "out", "text": "Absolutely. The progress in open models has been incredible this year."},
            {"direction": "in", "text": "Indeed. Looking forward to seeing where this project goes!"},
        ],
    },
]


def seed_conversations():
    """Create test conversations and messages."""
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        # Get the first active identity
        identity = session.query(Identity).filter_by(is_active=True).first()
        if not identity:
            print("ERROR: No active identity found. Please connect a Reddit account first.")
            return

        print(f"Using identity: {identity.display_name} (ID: {identity.id})")

        # Create external accounts and conversations
        base_time = datetime.utcnow() - timedelta(days=7)

        for conv_data in CONVERSATIONS:
            username = conv_data["username"]
            user_info = next((u for u in FAKE_USERS if u["username"] == username), None)
            if not user_info:
                continue

            # Check if external account exists
            ext_account = (
                session.query(ExternalAccount)
                .filter_by(provider_id="reddit", external_username=username)
                .first()
            )

            if not ext_account:
                ext_account = ExternalAccount(
                    provider_id="reddit",
                    external_username=username,
                    external_user_id=user_info["user_id"],
                    remote_status="active",
                )
                session.add(ext_account)
                session.flush()
                print(f"Created external account: {username}")

            # Check if conversation exists
            conversation = (
                session.query(Conversation)
                .filter_by(
                    provider_id="reddit",
                    counterpart_account_id=ext_account.id,
                    identity_id=identity.id,
                )
                .first()
            )

            if not conversation:
                conversation = Conversation(
                    provider_id="reddit",
                    external_conversation_id=f"conv_{username.lower()}_{random.randint(1000, 9999)}",
                    counterpart_account_id=ext_account.id,
                    identity_id=identity.id,
                )
                session.add(conversation)
                session.flush()
                print(f"Created conversation with: {username}")

            # Add messages
            existing_messages = (
                session.query(Message)
                .filter_by(conversation_id=conversation.id)
                .count()
            )

            if existing_messages == 0:
                msg_time = base_time + timedelta(days=random.randint(0, 5))

                for msg_data in conv_data["messages"]:
                    msg_time += timedelta(minutes=random.randint(5, 120))

                    message = Message(
                        provider_id="reddit",
                        external_message_id=f"msg_{random.randint(100000, 999999)}",
                        conversation_id=conversation.id,
                        identity_id=identity.id if msg_data["direction"] == "out" else None,
                        direction=msg_data["direction"],
                        sent_at=msg_time,
                        body_text=msg_data["text"],
                        remote_visibility="visible",
                    )
                    session.add(message)

                # Update conversation last_activity_at
                conversation.last_activity_at = msg_time

                print(f"  Added {len(conv_data['messages'])} messages to conversation with {username}")

            # Randomize the base time for next conversation
            base_time += timedelta(hours=random.randint(1, 24))

        session.commit()
        print("\nSeed data created successfully!")

    except Exception as e:
        session.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_conversations()
