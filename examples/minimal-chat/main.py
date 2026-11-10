"""minimal-chat entry point — assembles the app from the Semente framework.

Run with:  python main.py   (FastAPI on port 3000; the REST API is always
available, WhatsApp/A2A follow the channels in semente.yaml)
"""

from semente.api import SementeApp

app = SementeApp("semente.yaml").build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
