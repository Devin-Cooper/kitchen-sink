#!/usr/bin/env python3
"""
SoFurry EPUB Downloader using Selenium with automatic driver management
This version automatically installs and manages ChromeDriver
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from pathlib import Path
import argparse
import getpass
import os

class SoFurrySeleniumDownloader:
    def __init__(self, uid, output_dir="downloads", delay=2.0, headless=False):
        self.uid = uid
        self.base_url = "https://www.sofurry.com"
        self.output_dir = Path(output_dir).absolute()
        self.delay = delay
        self.output_dir.mkdir(exist_ok=True)
        
        # Setup Chrome options
        chrome_options = Options()
        
        # Set download directory
        prefs = {
            "download.default_directory": str(self.output_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "safebrowsing.disable_download_protection": True
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Anti-detection measures
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Headless mode if requested
        if headless:
            chrome_options.add_argument("--headless=new")  # New headless mode
            chrome_options.add_argument("--window-size=1920,1080")
        
        # Additional options for stability
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--disable-features=VizDisplayCompositor")
        
        try:
            # Automatically download and set up ChromeDriver
            print("Setting up ChromeDriver automatically...")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Remove webdriver property
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            print("✓ Browser initialized successfully")
            
        except Exception as e:
            print(f"Error initializing browser: {e}")
            print("\nTroubleshooting:")
            print("1. Make sure Google Chrome is installed")
            print("2. Try running: pip install --upgrade selenium webdriver-manager")
            raise
            
    def wait_for_element(self, by, value, timeout=10):
        """Wait for element with better error handling"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except:
            return None
            
    def login(self, username, password):
        """Login using Selenium"""
        print(f"Logging in as {username}...")
        
        # Navigate to main page
        self.driver.get(self.base_url)
        time.sleep(3)  # Wait for page load
        
        try:
            # Find and fill username field
            username_field = self.wait_for_element(By.ID, "LoginForm_sfLoginUsername")
            if not username_field:
                print("Could not find username field - page might have changed")
                return False
                
            username_field.clear()
            username_field.send_keys(username)
            
            # Find and fill password field
            password_field = self.driver.find_element(By.ID, "LoginForm_sfLoginPassword")
            password_field.clear()
            password_field.send_keys(password)
            
            # Submit form
            submit_button = self.driver.find_element(By.NAME, "yt1")
            submit_button.click()
            
            # Wait for login to complete
            time.sleep(5)
            
            # Check if logged in by looking for logout link or username
            page_source = self.driver.page_source.lower()
            if "logout" in page_source or username.lower() in page_source:
                print("✓ Login successful!")
                return True
            else:
                print("✗ Login failed - check credentials")
                # Save screenshot for debugging
                self.driver.save_screenshot(str(self.output_dir / "login_failed.png"))
                return False
                
        except Exception as e:
            print(f"Error during login: {e}")
            self.driver.save_screenshot(str(self.output_dir / "login_error.png"))
            return False
    
    def get_first_story_from_folder(self, folder_url, folder_title):
        """Get the first story from a folder"""
        try:
            print(f"    Checking folder: {folder_title}")
            print(f"      URL: {folder_url}")
            
            self.driver.get(folder_url)
            time.sleep(self.delay)
            
            # Check current URL after navigation
            current_url = self.driver.current_url
            print(f"      Current URL after navigation: {current_url}")
            
            # Check if we were redirected to login or another page
            if "login" in current_url.lower():
                print(f"      Redirected to login page - session may have expired")
                return None
            
            # Debug: Always save page source for the first few folders to see what we're getting
            debug_file = self.output_dir / f"folder_debug_{folder_title.replace(' ', '_').replace('/', '_')}.html"
            try:
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)
                print(f"      DEBUG: Saved page source to {debug_file.name}")
            except Exception as save_error:
                print(f"      Warning: Could not save debug file: {save_error}")
            
            # Find story links in the folder - try multiple approaches
            story_elements = []
            
            # Method 1: Target story links specifically in headline containers
            story_elements = self.driver.find_elements(By.CSS_SELECTOR, '.sf-story-big-headline a[href^="/view/"], .sf-story-headline a[href^="/view/"]')
            print(f"      Method 1 found {len(story_elements)} elements with specific story headline selectors")
            
            # Method 2: If that doesn't work, try broader story container approach
            if not story_elements:
                story_elements = self.driver.find_elements(By.CSS_SELECTOR, '.sf-story a[href^="/view/"], .sf-story-big a[href^="/view/"]')
                print(f"      Method 2 found {len(story_elements)} elements with story container selectors")
            
            # Method 3: Fall back to the original broad search but filter out non-story links
            if not story_elements:
                all_view_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href^="/view/"]')
                print(f"      Method 3 found {len(all_view_links)} total /view/ links")
                
                # Filter out known non-story patterns
                for link in all_view_links:
                    try:
                        href = link.get_attribute('href')
                        if href and '/view/' in href:
                            # Skip subscription, user profile, and other non-story links
                            if not any(exclude in href for exclude in ['subscribeFolder', 'user/', 'character/', 'tag/']):
                                # Check if it's a numeric story ID
                                match = re.search(r'/view/(\d+)$', href)
                                if match:
                                    story_elements.append(link)
                    except:
                        continue
                print(f"      Method 3 filtered to {len(story_elements)} actual story links")
            
            if story_elements:
                first_story = story_elements[0]
                href = first_story.get_attribute('href')
                title = first_story.text.strip()
                
                print(f"      First story element - href: {href}, title: '{title}'")
                
                if href and '/view/' in href:
                    match = re.search(r'/view/(\d+)', href)
                    if match:
                        story_id = match.group(1)
                        print(f"      ✓ Found first story in folder: {title} (ID: {story_id})")
                        return (story_id, f"[FOLDER: {folder_title}] {title}")
                        
            print(f"      No valid stories found in folder: {folder_title}")
            return None
            
        except Exception as e:
            print(f"      Error accessing folder '{folder_title}': {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_story_links(self):
        """Get all story links from user page, including folders"""
        all_stories = []
        seen_story_ids = set()
        page = 1
        max_pages = 100  # Safety limit
        consecutive_duplicate_pages = 0
        last_page_count = 0
        
        print(f"\nFetching stories from user {self.uid}...")
        
        while page <= max_pages:
            url = f"{self.base_url}/browse/user/stories?uid={self.uid}&stories-page={page}"
            print(f"Fetching page {page}...")
            
            self.driver.get(url)
            time.sleep(self.delay)
            
            # Check if we're logged in
            if "login" in self.driver.current_url.lower() and "browse" not in self.driver.current_url:
                print("Session expired - need to log in again")
                return []
            
            # Find story links
            story_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href^="/view/"]')
            
            # Find folder links (only on first page typically)
            folder_elements = []
            if page == 1:
                folder_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/browse/folder/stories"]')
                if folder_elements:
                    print(f"  Found {len(folder_elements)} folders on page {page}")
            
            if not story_elements and not folder_elements:
                print(f"No stories or folders found on page {page}")
                break
            
            page_stories = 0
            new_stories_on_page = 0
            
            # Process individual stories
            for element in story_elements:
                try:
                    href = element.get_attribute('href')
                    title = element.text.strip()
                    
                    if href and title and '/view/' in href:
                        match = re.search(r'/view/(\d+)', href)
                        if match:
                            story_id = match.group(1)
                            page_stories += 1
                            
                            # Only add if we haven't seen this story before
                            if story_id not in seen_story_ids:
                                seen_story_ids.add(story_id)
                                all_stories.append((story_id, title))
                                new_stories_on_page += 1
                except:
                    continue
            
            # Process folders (only on first page)
            if page == 1:
                print(f"  Processing {len(folder_elements)} folders...")
                
                # Extract all folder info BEFORE navigating (to avoid stale element errors)
                folder_info_list = []
                for i, folder_element in enumerate(folder_elements, 1):
                    try:
                        folder_href = folder_element.get_attribute('href')
                        folder_title = folder_element.get_attribute('title') or 'Unnamed Folder'
                        if folder_href and '/browse/folder/stories' in folder_href:
                            folder_info_list.append((folder_href, folder_title))
                        else:
                            print(f"  Folder {i}: Invalid href: {folder_href}")
                    except Exception as e:
                        print(f"  Folder {i}: Error extracting info: {e}")
                        continue
                
                print(f"  Extracted info for {len(folder_info_list)} valid folders")
                
                # Now process each folder (safe from stale element errors)
                for i, (folder_href, folder_title) in enumerate(folder_info_list, 1):
                    try:
                        print(f"  Folder {i}/{len(folder_info_list)}: {folder_title}")
                        
                        # Get the first story from this folder
                        folder_story = self.get_first_story_from_folder(folder_href, folder_title)
                        if folder_story:
                            story_id, title = folder_story
                            if story_id not in seen_story_ids:
                                seen_story_ids.add(story_id)
                                all_stories.append((story_id, title))
                                new_stories_on_page += 1
                            else:
                                print(f"    Story {story_id} already seen, skipping folder")
                        else:
                            print(f"    No story found in folder: {folder_title}")
                    except Exception as e:
                        print(f"    Error processing folder {i} ({folder_title}): {e}")
                        continue
            
            print(f"  Found {page_stories} individual stories on page {page} ({new_stories_on_page} new items total)")
            
            # Break conditions:
            # 1. No stories found at all
            if page_stories == 0 and (page > 1 or len(folder_elements) == 0):
                print("  No stories found, reached end")
                break
            
            # 2. No new stories found (all were duplicates) - but allow first page with folders
            if new_stories_on_page == 0 and not (page == 1 and folder_elements):
                print("  All stories on this page were duplicates, reached end")
                break
            
            # 3. Same number of stories as last page (potential pagination loop)
            if page_stories == last_page_count and page > 1:
                consecutive_duplicate_pages += 1
                if consecutive_duplicate_pages >= 3:
                    print("  Detected pagination loop (same story count for 3+ pages), stopping")
                    break
            else:
                consecutive_duplicate_pages = 0
            
            last_page_count = page_stories
            page += 1
        
        if page > max_pages:
            print(f"  Reached maximum page limit ({max_pages}), stopping")
            
        # Count individual stories vs folder stories
        folder_stories = sum(1 for _, title in all_stories if title.startswith('[FOLDER:'))
        individual_stories = len(all_stories) - folder_stories
        
        print(f"Collected {len(all_stories)} total items from {page-1} pages:")
        print(f"  - {individual_stories} individual stories")
        print(f"  - {folder_stories} folder collections")
        
        return all_stories
    
    def wait_for_download(self, filename, timeout=30):
        """Wait for download to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if file exists and is not a temp file
            if filename.exists():
                # Make sure it's not still downloading
                time.sleep(1)
                size1 = filename.stat().st_size if filename.exists() else 0
                time.sleep(1)
                size2 = filename.stat().st_size if filename.exists() else 0
                
                if size1 == size2 and size1 > 0:
                    return True
                    
            # Check for Chrome temp files
            temp_files = list(self.output_dir.glob("*.crdownload"))
            if temp_files:
                time.sleep(1)
            else:
                time.sleep(0.5)
                
        return filename.exists()
    
    def is_story_already_downloaded(self, story_id, title):
        """Check if story is already downloaded using multiple methods"""
        safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:100].strip()
        safe_title = safe_title.replace(' ', '_')
        
        # Try to find the file with flexible naming patterns
        possible_files = [
            self.output_dir / f"{story_id}_{safe_title}.epub",
            self.output_dir / f"{safe_title}.epub", 
            self.output_dir / f"{story_id}.epub"
        ]
        
        # Check exact matches first
        for pf in possible_files:
            if pf.exists():
                return True, f"exact match: {pf.name}"
        
        # Check all existing EPUB files for story ID in filename
        existing_epubs = list(self.output_dir.glob("*.epub"))
        for epub_file in existing_epubs:
            # Check if story ID appears anywhere in the filename
            if story_id in epub_file.stem:
                return True, f"ID match: {epub_file.name}"
        
        # Check for similar titles (fuzzy matching)
        cleaned_title = re.sub(r'[^a-zA-Z0-9]', '', title.lower())
        if cleaned_title:  # Only if title has alphanumeric characters
            for epub_file in existing_epubs:
                epub_title = re.sub(r'[^a-zA-Z0-9]', '', epub_file.stem.lower())
                # Remove story ID from epub filename for comparison
                epub_title_clean = re.sub(r'\d+_?', '', epub_title)
                
                # Check if titles are similar (contains or very close)
                if cleaned_title in epub_title_clean or epub_title_clean in cleaned_title:
                    if len(cleaned_title) > 3 and len(epub_title_clean) > 3:  # Avoid false positives on short titles
                        return True, f"title match: {epub_file.name}"
        
        return False, None

    def download_story(self, story_id, title):
        """Download a single story"""
        # Check if already downloaded
        already_exists, match_reason = self.is_story_already_downloaded(story_id, title)
        if already_exists:
            print(f"  Skipping '{title}' - already exists ({match_reason})")
            return True
        
        safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:100].strip()
        safe_title = safe_title.replace(' ', '_')
        
        # Preferred filename for new downloads
        preferred_filename = self.output_dir / f"{story_id}_{safe_title}.epub"
        
        # Check for any recent EPUB files before download
        existing_epubs = set(self.output_dir.glob("*.epub"))
        
        epub_url = f"{self.base_url}/export/ePub?id={story_id}"
        
        try:
            # Navigate to download URL
            self.driver.get(epub_url)
            
            # Wait a bit for download to start
            time.sleep(2)
            
            # Find new EPUB files
            new_epubs = set(self.output_dir.glob("*.epub")) - existing_epubs
            
            if new_epubs:
                downloaded_file = list(new_epubs)[0]
                print(f"  ✓ Downloaded: '{title}' as {downloaded_file.name}")
                
                # Rename to our preferred format if different
                if downloaded_file != preferred_filename:
                    try:
                        downloaded_file.rename(preferred_filename)
                        print(f"    Renamed to: {preferred_filename.name}")
                    except:
                        pass  # Keep original name if rename fails
                        
                return True
            else:
                # Wait longer for download
                if self.wait_for_download(preferred_filename, timeout=15):
                    print(f"  ✓ Downloaded: '{title}'")
                    return True
                else:
                    print(f"  ⚠ Download may have failed for: '{title}'")
                    return False
                    
        except Exception as e:
            print(f"  ✗ Error downloading '{title}': {e}")
            return False
    
    def download_all(self):
        """Download all stories"""
        stories = self.get_story_links()
        
        if not stories:
            print("No stories found!")
            return
            
        print(f"\nFound {len(stories)} stories total")
        print("Starting downloads...")
        print("-" * 50)
        
        successful = 0
        failed = 0
        
        for i, (story_id, title) in enumerate(stories, 1):
            print(f"\n[{i}/{len(stories)}] {title}")
            
            if self.download_story(story_id, title):
                successful += 1
            else:
                failed += 1
                
            time.sleep(self.delay)
            
        print("\n" + "=" * 50)
        print(f"Download complete!")
        print(f"✓ Successful: {successful}")
        print(f"✗ Failed: {failed}")
        print(f"Files saved to: {self.output_dir}")
    
    def close(self):
        """Close the browser"""
        self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='Download EPUBs using Selenium (Auto-install version)')
    parser.add_argument('uid', type=int, help='User ID')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (no browser window)')
    parser.add_argument('-o', '--output', default='downloads', help='Output directory')
    parser.add_argument('-d', '--delay', type=float, default=2.0, help='Delay between downloads')
    
    args = parser.parse_args()
    
    # Get credentials
    print("SoFurry EPUB Downloader (Selenium Auto)")
    print("=" * 40)
    username = input("SoFurry username: ")
    password = getpass.getpass("SoFurry password: ")
    
    # Create downloader
    try:
        downloader = SoFurrySeleniumDownloader(
            args.uid, 
            args.output, 
            delay=args.delay,
            headless=args.headless
        )
    except Exception as e:
        print(f"\nFailed to initialize browser: {e}")
        return
    
    try:
        if downloader.login(username, password):
            downloader.download_all()
        else:
            print("\nLogin failed. Please check your credentials.")
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        print("\nClosing browser...")
        downloader.close()

if __name__ == "__main__":
    main()