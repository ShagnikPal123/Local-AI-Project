"""Example usage of the intelligent router."""

from router import Router


def main():
    """Demonstrate router functionality."""
    print("Initializing intelligent router...\n")
    router = Router()

    # Show current system status
    status = router.get_status()
    print("System Status:")
    print(f"  Device Tier: {status['device_tier']}")
    print(f"  Online: {status['online']}")
    print(f"  Ollama Available: {status['ollama_available']}")
    print(f"  Perplexity Available: {status['perplexity_available']}")
    print(f"  Preferred Online Provider: {status['preferred_online_provider']}\n")

    print("Device Profile:")
    for key, value in status["device_profile"].items():
        print(f"  {key}: {value}")
    print()

    # Example chat messages
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "What is Python?"},
    ]

    print("Sending chat request...")
    try:
        response, provider = router.chat(messages)
        print(f"Response from {provider}: {response}\n")
    except Exception as e:
        print(f"Error: {e}\n")


if __name__ == "__main__":
    main()
