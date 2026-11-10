"""Groot entry point — assembles the app from the Semente framework.

Interactive chat:  semente launch streamlit
HTTP interfaces:   python main.py   (REST always on; WhatsApp/A2A when enabled)
"""

from semente.api import SementeApp

app = SementeApp("semente.yaml").build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
