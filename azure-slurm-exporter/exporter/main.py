import asyncio
from exporter.exporter import main as async_main

def main():
    asyncio.run(async_main())

if __name__=="__main__":
    main()