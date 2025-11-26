import os
import sys
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from queue import Queue

# Configuration for file mapping
FILE_TYPES = {
    'pdf':  ['.pdf'],
    'docs': ['.doc', '.docx', '.txt', '.rtf'],
    'ppt':  ['.ppt', '.pptx'],
    'xls':  ['.xls', '.xlsx', '.csv'],
    'zip':  ['.zip', '.rar', '.7z', '.tar', '.gz'],
    'images': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg']
}

class WebScraper:
    def __init__(self, base_url, target_extensions):
        """
        Initialize the WebScraper.
        :param base_url: The starting URL (and domain constraint).
        :param target_extensions: List of file extensions to download (e.g., ['.pdf', '.docx']).
        """
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.target_extensions = target_extensions
        
        # BFS Queue and Visited Set
        self.queue = Queue()
        self.visited_urls = set()
        
        # Headers to mimic a real browser to avoid 403 Forbidden
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Create base download directory
        self.base_download_path = "downloads"
        self.create_directories()

    def create_directories(self):
        """Creates the directory structure based on keys in FILE_TYPES."""
        if not os.path.exists(self.base_download_path):
            os.makedirs(self.base_download_path)
            
        for folder in FILE_TYPES.keys():
            path = os.path.join(self.base_download_path, folder)
            if not os.path.exists(path):
                os.makedirs(path)

    def get_download_folder(self, extension):
        """Determines the correct subfolder based on file extension."""
        for folder, exts in FILE_TYPES.items():
            if extension in exts:
                return folder
        return "others"

    def is_internal_link(self, url):
        """Checks if a URL belongs to the target domain."""
        return urlparse(url).netloc == self.domain

    def is_target_file(self, url):
        """Checks if the URL ends with one of the target extensions."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in self.target_extensions)

    def fetch_page(self, url):
        """
        Fetches the content of a page with retry logic.
        :return: Response object or None if failed.
        """
        print(f"[*] Visiting: {url}")
        retries = 3
        for i in range(retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    return response
                elif response.status_code == 404:
                    print(f"    [!] 404 Not Found: {url}")
                    return None
                elif response.status_code == 403:
                    print(f"    [!] 403 Forbidden: {url}")
                    return None
            except requests.exceptions.RequestException as e:
                print(f"    [!] Connection error (Attempt {i+1}/{retries}): {e}")
                time.sleep(2)
        return None

    def download_file(self, file_url):
        """Downloads a specific file to the appropriate folder."""
        try:
            # Parse filename from URL
            parsed_url = urlparse(file_url)
            filename = unquote(os.path.basename(parsed_url.path))
            
            # Clean filename to avoid filesystem errors
            filename = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in (' ', '.', '_', '-')]).strip()
            if not filename:
                filename = "downloaded_file"

            # Determine folder
            _, ext = os.path.splitext(filename)
            folder = self.get_download_folder(ext.lower())
            save_path = os.path.join(self.base_download_path, folder, filename)

            # Check for duplicates
            if os.path.exists(save_path):
                print(f"    [-] Skipping duplicate: {filename}")
                return

            print(f"    [+] Found file: {filename}")
            
            # Stream download
            with requests.get(file_url, headers=self.headers, stream=True, timeout=20) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            print(f"    [V] Downloaded: {save_path}")

        except Exception as e:
            print(f"    [X] Failed to download {file_url}: {e}")

    def extract_links_and_files(self, html_content, current_url):
        """
        Parses HTML to find:
        1. New internal links to crawl.
        2. Files to download.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        new_links = []
        
        # Iterate over all 'a' tags with href attribute
        for tag in soup.find_all(['a', 'link'], href=True):
            href = tag['href']
            full_url = urljoin(current_url, href)
            
            # Remove fragments (#) for cleaner URL tracking
            full_url = full_url.split('#')[0]

            if not full_url:
                continue

            # Case 1: It is a file we want to download
            if self.is_target_file(full_url):
                self.download_file(full_url)
            
            # Case 2: It is a webpage to crawl (internal only)
            elif self.is_internal_link(full_url) and full_url not in self.visited_urls:
                new_links.append(full_url)

        # Also check images if requested (searching <img> tags)
        if any(ext in self.target_extensions for ext in FILE_TYPES['images']):
            for img in soup.find_all('img', src=True):
                src = img['src']
                full_url = urljoin(current_url, src)
                if self.is_target_file(full_url):
                    self.download_file(full_url)

        return new_links

    def run(self):
        """Main BFS crawling loop."""
        self.queue.put(self.base_url)
        
        try:
            while not self.queue.empty():
                current_url = self.queue.get()
                
                if current_url in self.visited_urls:
                    continue
                
                self.visited_urls.add(current_url)
                
                # Fetch page content
                response = self.fetch_page(current_url)
                if response:
                    # Extract files and get new links
                    # We only parse HTML content-types
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'text/html' in content_type:
                        links = self.extract_links_and_files(response.text, current_url)
                        for link in links:
                            if link not in self.visited_urls:
                                self.queue.put(link)
                                
        except KeyboardInterrupt:
            print("\n[!] Stopping Scraper...")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_extensions_by_mode(mode):
    """Returns list of extensions based on user menu choice."""
    if mode == 1:
        return FILE_TYPES['pdf']
    elif mode == 2:
        return FILE_TYPES['docs'] + FILE_TYPES['ppt'] + FILE_TYPES['xls'] + FILE_TYPES['zip'] + FILE_TYPES['docs']
    elif mode == 3:
        all_exts = []
        for ext_list in FILE_TYPES.values():
            all_exts.extend(ext_list)
        return all_exts
    return []

def main():
    while True:
        clear_screen()
        print("===================================================")
        print("        ADVANCED WEB SCRAPER TOOL (Python)")
        print("===========        Made by CENOZEX       ========")
        print("===================================================")
        print("======Scrapes Only Publicly available file========")
        print(" [1] Scrape all PDF files")
        print(" [2] Scrape all Notes / DOCX / PPTX / TXT / ZIP")
        print(" [3] Scrape all file types (inc. Images)")
        print(" [4] Exit")
        print("=========================================")
        
        choice = input("Select an option (1-4): ").strip()
        
        if choice == '4':
            print("Exiting...")
            sys.exit()
            
        if choice not in ['1', '2', '3']:
            print("Invalid selection. Try again.")
            time.sleep(1)
            continue
            
        target_url = input("\nEnter target website URL (e.g., https://example.com): ").strip()
        
        if not target_url.startswith('http'):
            target_url = 'https://' + target_url

        try:
            # Validate URL format
            result = urlparse(target_url)
            if not all([result.scheme, result.netloc]):
                raise ValueError
        except:
            print("Invalid URL format.")
            time.sleep(2)
            continue

        # Configure extensions
        target_exts = get_extensions_by_mode(int(choice))
        
        print(f"\nInitializing scraper for: {target_url}")
        print(f"Looking for: {target_exts}")
        print("Press Ctrl+C to stop manually.\n")
        time.sleep(2)

        # Run Scraper
        scraper = WebScraper(target_url, target_exts)
        scraper.run()
        
        print("\nScanning complete.")
        input("Press Enter to return to menu...")

if __name__ == "__main__":
    main()

"""
## INSTALLATION
1. Ensure Python 3.x is installed.
2. Install required dependencies via terminal/command prompt:
   
   pip install requests beautifulsoup4

## HOW TO RUN
1. Save the code above as `scraper.py`
2. Open your terminal or command prompt.
3. Navigate to the folder where you saved the file.
4. Run the script:

   python scraper.py

5. Follow the on-screen menu instructions.
   - Files will be saved in a `downloads` folder created in the same directory.
"""
