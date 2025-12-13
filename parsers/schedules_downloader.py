import asyncio
import os
from urllib.parse import unquote

from aiohttp import ClientSession
from bs4 import BeautifulSoup


async def fetch_html(session: ClientSession, url: str) -> str:
    async with session.get(url, raise_for_status=True) as response:
        return await response.text()


class SZGMUParser:
    def __init__(self, base_url: str, schedule_url: str, output_dir: str) -> None:
        self.base_url = base_url
        self.schedule_url = schedule_url
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_links(
            self,
            html: str,
            href_pattern: str,
            container_selector: str | None = None,
            prefix_with_base_url: bool = True
    ) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(container_selector) if container_selector else soup
        links = []
        if not container:
            return []

        for a_tag in container.select(f"a[href{href_pattern}]"):
            link = a_tag.get("href")
            if prefix_with_base_url and not link.startswith("http"):
                link = f"{self.base_url}{link}"
            links.append(link)
        return links

    def extract_links_to_specializations(self, html: str) -> list[str]:
        return self.extract_links(
            html,
            href_pattern='^="/rus/m/"',
            container_selector="div.b-text"
        )

    def extract_pdf_links(self, html: str) -> list[str]:
        return self.extract_links(html, href_pattern='$=".pdf"')

    async def download_file(self, session: ClientSession, url: str) -> None:
        async with session.get(url, raise_for_status=True) as response:
            filename = unquote(os.path.basename(url.split("?")[0]))
            filepath = os.path.join(self.output_dir, filename)

            with open(filepath, "wb") as f:
                while chunk := await response.content.read(8192):
                    f.write(chunk)

    async def run(self) -> None:
        async with ClientSession() as session:
            schedule_html = await fetch_html(session, self.schedule_url)
            specializations_links = self.extract_links_to_specializations(schedule_html)

            for specialization_url in specializations_links:
                specialization_html = await fetch_html(session, specialization_url)
                pdf_links = self.extract_pdf_links(specialization_html)
                for pdf_link in pdf_links:
                    await self.download_file(session, pdf_link)


if __name__ == "__main__":
    parser = SZGMUParser(
        base_url="https://szgmu.ru",
        schedule_url="https://szgmu.ru/rus/m/518/",
        output_dir=r"..\schedule_data"
    )
    asyncio.run(parser.run())
