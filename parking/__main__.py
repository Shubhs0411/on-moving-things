import os
import uvicorn


def main():
    port = int(os.environ.get("PARK_PORT", 8001))
    uvicorn.run("parking.app:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()
