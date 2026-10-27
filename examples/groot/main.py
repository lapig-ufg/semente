"""Groot entry point — assembles the app from the Semente framework.

Interactive chat:  semente launch streamlit
WhatsApp webhook:  python main.py   (when the whatsapp channel is enabled)
"""

from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
