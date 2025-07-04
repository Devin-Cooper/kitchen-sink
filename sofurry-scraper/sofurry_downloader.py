#!/usr/bin/env python3
"""
SoFurry EPUB Downloader
Downloads all stories from a specific user as EPUB files
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re
from urllib.parse import urljoin, urlparse, parse_qs
import argparse
from pathlib import Path

class SoFurryDownloader:
    def __init__(self, uid, output_dir="downloads", delay=1.0):
        """
        Initialize the downloader
        
        Args:
            uid: User ID to download stories from
            output_dir: Directory to save EPUB files
            delay: Delay between requests in seconds (be respectful to the server)
        """
        self.uid = uid
        self.base_url = "https://www.sofurry.com"
        self.output_dir = Path(output_dir)
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(exist_ok=True)
        
    def get_story_ids(self, page=1, stories_per_page=45):
        """
        Get all story IDs from a user's story listing page
        
        Args:
            page: Page number to fetch
            stories_per_page: Number of stories per page
            
        Returns:
            List of tuples (story_id, story_title)
        """
        url = f"{self.base_url}/browse/user/stories?uid={self.uid}&stories-display={stories_per_page}&page={page}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching page {page}: {e}")
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        stories = []
        
        # Find all story links
        story_links = soup.find_all('a', href=re.compile(r'^/view/\d+$'))
        
        for link in story_links:
            href = link.get('href', '')
            title = link.get_text(strip=True)
            
            # Extract story ID from href
            match = re.search(r'/view/(\d+)', href)
            if match:
                story_id = match.group(1)
                stories.append((story_id, title))
                
        return stories
    
    def get_all_stories(self, stories_per_page=45):
        """
        Get all stories from all pages
        
        Returns:
            List of tuples (story_id, story_title)
        """
        all_stories = []
        page = 1
        
        print(f"Fetching stories from user {self.uid}...")
        
        while True:
            stories = self.get_story_ids(page, stories_per_page)
            
            if not stories:
                break
                
            all_stories.extend(stories)
            print(f"Found {len(stories)} stories on page {page}")
            
            # Check if there might be more pages
            if len(stories) < stories_per_page:
                break
                
            page += 1
            time.sleep(self.delay)
            
        return all_stories
    
    def sanitize_filename(self, filename):
        """
        Sanitize filename for safe file system usage
        """
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Replace multiple spaces with single space
        filename = re.sub(r'\s+', ' ', filename)
        # Trim whitespace
        filename = filename.strip()
        # Limit length
        if len(filename) > 200:
            filename = filename[:200]
        return filename
    
    def download_epub(self, story_id, title):
        """
        Download a single story as EPUB
        
        Args:
            story_id: Story ID to download
            title: Story title (for filename)
            
        Returns:
            True if successful, False otherwise
        """
        epub_url = f"{self.base_url}/export/ePub?id={story_id}"
        
        # Create safe filename
        safe_title = self.sanitize_filename(title)
        filename = self.output_dir / f"{story_id}_{safe_title}.epub"
        
        # Skip if already downloaded
        if filename.exists():
            print(f"Skipping '{title}' - already downloaded")
            return True
        
        try:
            response = self.session.get(epub_url, stream=True)
            response.raise_for_status()
            
            # Save the file
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            print(f"Downloaded: '{title}' -> {filename.name}")
            return True
            
        except requests.RequestException as e:
            print(f"Error downloading '{title}' (ID: {story_id}): {e}")
            return False
    
    def download_all(self):
        """
        Download all stories from the user
        """
        # Get all story IDs
        stories = self.get_all_stories()
        
        if not stories:
            print("No stories found!")
            return
        
        print(f"\nFound {len(stories)} stories total")
        print(f"Starting downloads to {self.output_dir}/")
        print("-" * 50)
        
        # Download each story
        successful = 0
        failed = 0
        
        for i, (story_id, title) in enumerate(stories, 1):
            print(f"\n[{i}/{len(stories)}] ", end="")
            
            if self.download_epub(story_id, title):
                successful += 1
            else:
                failed += 1
                
            # Be respectful to the server
            if i < len(stories):
                time.sleep(self.delay)
        
        print("\n" + "=" * 50)
        print(f"Download complete!")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Files saved to: {self.output_dir.absolute()}")

def main():
    parser = argparse.ArgumentParser(description='Download EPUB files from SoFurry user')
    parser.add_argument('uid', type=int, help='User ID to download stories from')
    parser.add_argument('-o', '--output', default='downloads', help='Output directory (default: downloads)')
    parser.add_argument('-d', '--delay', type=float, default=1.0, help='Delay between requests in seconds (default: 1.0)')
    parser.add_argument('-s', '--stories-per-page', type=int, default=45, help='Stories per page (default: 45)')
    
    args = parser.parse_args()
    
    # Create downloader and run
    downloader = SoFurryDownloader(args.uid, args.output, args.delay)
    downloader.download_all()

if __name__ == "__main__":
    main()