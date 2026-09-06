#!/usr/bin/env python3
"""Quick one-off chat with Nyx Pulse - with multi-mode agent pool support."""

import sys
import argparse
from multi_mode_chat import get_multi_mode_chat
from colorama import init, Fore, Style

init(autoreset=True)


def quick_chat(question: str, attribute_id: str | None = None, 
              verbose: bool = False, no_multimode: bool = False) -> None:
    """Ask a single question and print the response."""
    
    if no_multimode:
        # Use original single-agent mode
        from chat_service import ChatService
        service = ChatService(attribute_id=attribute_id)
        
        try:
            print(f"{Fore.BLUE}You:{Style.RESET_ALL} {question}\n")
            response, provider = service.chat(question)
            print(f"{Fore.GREEN}Nyx Pulse ({provider}):{Style.RESET_ALL}")
            print(f"  {response}\n")
        except Exception as error:
            print(f"{Fore.RED}Error: {error}{Style.RESET_ALL}\n")
            sys.exit(1)
    else:
        # Use multi-mode agent pool
        multi_chat = get_multi_mode_chat(use_pool=True)
        
        try:
            print(f"{Fore.BLUE}You:{Style.RESET_ALL} {question}\n")
            response, provider, metadata = multi_chat.chat(
                question, 
                attribute_id=attribute_id,
                verbose=verbose
            )
            print(f"{Fore.GREEN}Nyx Pulse ({provider}):{Style.RESET_ALL}")
            print(f"  {response}\n")
            
            # Show metadata if verbose
            if verbose and metadata:
                print(f"{Fore.CYAN}[Metadata]{Style.RESET_ALL}")
                for key, value in metadata.items():
                    print(f"  {key}: {value}")
                print()
        except Exception as error:
            print(f"{Fore.RED}Error: {error}{Style.RESET_ALL}\n")
            sys.exit(1)


def main():
    """Parse args and run quick chat."""
    parser = argparse.ArgumentParser(
        description="Quick chat with Nyx Pulse - multi-mode agent pool enabled by default",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python quick_chat.py "What is Python?"
  python quick_chat.py "How do I use async?" --attribute coding
  python quick_chat.py "Debug this error" --attribute debugging
  python quick_chat.py "Solve this problem" --verbose
  python quick_chat.py "Quick question" --no-multimode
"""
    )
    parser.add_argument("question", help="The question to ask the assistant")
    parser.add_argument(
        "--attribute",
        default=None,
        help="Optional attribute (coding, debugging, explain, etc.)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode to see task analysis and agent details"
    )
    parser.add_argument(
        "--no-multimode",
        action="store_true",
        help="Disable multi-mode agent pool (use single agent)"
    )
    
    args = parser.parse_args()
    quick_chat(args.question, attribute_id=args.attribute, 
              verbose=args.verbose, no_multimode=args.no_multimode)


if __name__ == "__main__":
    main()
