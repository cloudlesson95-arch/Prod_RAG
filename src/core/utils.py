import os
from src.routing.model_resolver import get_model

def create_llm(provider: str):
    """Factory function to create LLM instances based on the provider name.
    
    Args:
        provider: The name of the LLM provider ('gemini' or 'groq').
        
    Returns:
        The appropriate LLM instance for the specified provider.
        
    Raises:
        ValueError: If an unknown provider is specified.
    """
    model = get_model(provider)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model = model,
            temperature=0,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    elif provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model = model,
            temperature=0,
            groq_api_key = os.getenv("GROQ_API_KEY")
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
