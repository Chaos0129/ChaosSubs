import sys
import uvicorn

if __name__ == "__main__":
    dev = "--dev" in sys.argv
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=dev)
