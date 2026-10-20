import os
import uuid
import base64
import wave

from pathlib import Path
from google import genai

from semente.logging import log_debug, log_error
from semente.tools.types import Audio


def generate_speech(text: str, user_id: str = "default") -> Audio:
    """
    Generates audio speech from the given text using Google's Gemini model.
    
    It must be called last; this will terminate the processing and send response to user.
    
    Args:
        text (str): The text to be converted into speech.
        
    Returns:
        ToolResult: The result containing the message and the audio media.
    """
    try:
        client = genai.Client()
        log_debug("Generating speech", center=True)
        log_debug(text)
        
        # ponytail: TTS model + voice style are domain-tunable; model via env, prompt hardcoded for now.
        prompt = f"Say it in a simple and direct way, use a very light accent and the slang of the ag context: {text}"
        
        interaction = client.interactions.create(
            model=os.getenv("TTS_MODEL", "gemini-3.1-flash-tts-preview"),
            input=prompt,
            response_format={"type": "audio"},
            generation_config={
                "speech_config": [
                    {"voice": "Kore"}
                ]
            }
        )
        
        if interaction.output_audio and interaction.output_audio.data:
            # The new format returns the PCM base64-encoded directly here
            audio_bytes = base64.b64decode(interaction.output_audio.data)
            
            # Directory path calculation
            storage_dir = Path.cwd() / "tmp" / "audio" / user_id
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"speech{uuid.uuid4().hex[:8]}.wav"
            file_path = storage_dir / filename
            
            # Writes the temporary WAV file from the returned PCM
            framerate = 24000  # Default Gemini TTS sample rate
            with wave.open(str(file_path), "wb") as wav_file:
                wav_file.setnchannels(1)      # Mono
                wav_file.setsampwidth(2)     # 16-bit
                wav_file.setframerate(framerate)
                wav_file.writeframes(audio_bytes)
            
            # --- FFMPEG environment setup for conversion ---
            ffmpeg_env_path = os.getenv("FFMPEG_PATH")
            if ffmpeg_env_path:
                os.environ["PATH"] += os.pathsep + ffmpeg_env_path
            
            # --- WAV to OGG conversion using Pydub ---
            try:
                from pydub import AudioSegment
                # Loads the generated WAV file
                audio = AudioSegment.from_wav(str(file_path))
                
                # Sets the new path with the .ogg extension
                ogg_path = file_path.with_suffix(".ogg")
                
                # Exports as OGG with the libopus codec (ideal for WhatsApp)
                audio.export(str(ogg_path), format="ogg", codec="libopus")
                
                # Removes the temporary WAV file to save space
                os.remove(file_path)
                
                # Updates the final file pointer to the OGG
                file_path = ogg_path

                result = Audio(filepath=str(file_path), mime_type="audio/ogg")

                return result
                
            except ImportError:
                log_error("pydub is not installed.")
                
            except Exception as e:
                log_error(f"Audio conversion failed: {e}.")
                    
    except Exception as e:
        log_error(f"Audio generation failed: {e}.")
    
    return None
        