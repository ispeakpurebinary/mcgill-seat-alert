from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from pushover_complete import PushoverAPI
from tenacity import retry, stop_after_attempt, wait_fixed
import os
import time
import json
import argparse
import logging
from requests.exceptions import RequestException
import traceback


# Use environment variables for Pushover credentials
PUSHOVER_USER_KEY = os.environ.get('PUSHOVER_USER_KEY')
PUSHOVER_API_TOKEN = os.environ.get('PUSHOVER_API_TOKEN')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_config():
    # Parse command-line arguments and load configuration from JSON file
    parser = argparse.ArgumentParser(description='Check course availability at McGill')
    parser.add_argument('--config', default='config.json', help='Path to the configuration file')
    args = parser.parse_args()

    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logging.error(f"Config file not found: {args.config}")
        return None
    except json.JSONDecodeError:
        logging.error(f"Error reading config file: {args.config}")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def load_webpage(driver, url):
    # Load webpage with retry mechanism in case of failure
    driver.get(url)
    logging.info("Webpage loaded successfully.")

def send_notification(title, message):
    # Send push notification using Pushover API
    try:
        pushover = PushoverAPI(PUSHOVER_API_TOKEN)
        pushover.send_message(PUSHOVER_USER_KEY, message, title=title)
        logging.info(f"Notification sent: {title}")
    except Exception as e:
        logging.error(f"Failed to send notification: {str(e)}")

def scroll_to_element(driver, element):
    # Scroll to the specified element to ensure it's in view
    actions = ActionChains(driver)
    actions.move_to_element(element).perform()

def get_course_availability(driver, course):
    # Check availability for a specific course
    try:
        logging.info(f"Searching for course: {course}")
        wait = WebDriverWait(driver, 20)
        course_box = wait.until(
            EC.presence_of_element_located((By.XPATH, f"//div[contains(@class, 'course_box') and contains(., '{course}')]"))
        )
        logging.info(f"Found course box for: {course}")
        scroll_to_element(driver, course_box)
        
        sections = course_box.find_elements(By.XPATH, ".//div[contains(@class, 'selection_row')]")
        logging.info(f"sections {sections}")
        logging.info(f"Found {len(sections)} sections for course: {course}")
        
        available_sections = []
        
        for section in sections:
            try:
                if "Lec" in section.text:
                    # Extract CRN and check for open seats or waitlist availability
                    crn = section.find_element(By.XPATH, ".//span[@class='crn_value']").text
                    logging.info(f"crns {crn}")
                    
                    seats_element = section.find_element(By.XPATH, ".//span[contains(@class, 'leftnclear') and contains(., 'Seats:')]")
                    if "Full" not in seats_element.text:
                        available_sections.append((crn, "Open seats"))
                        continue
                    
                    waitlist_element = section.find_element(By.XPATH, ".//span[contains(@class, 'legend_waitlist')]")
                    if "None" not in waitlist_element.text:
                        available_sections.append((crn, "Waitlist"))
            except NoSuchElementException as e:
                logging.warning(f"Error processing section in {course}: {str(e)}")
        
        return available_sections
    except TimeoutException:
        pass
        logging.error(f"Timeout while searching for course: {course}")
    except Exception as e:
        pass
        logging.error(f"Error checking availability for {course}: {str(e)}")
    return []

def setup_driver():
    # Configure and initialize Chrome WebDriver
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=800,1080')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def perform_web_task():
    logging.info("Starting web task...")
    
    # Load configuration
    config = get_config()
    if not config:
        return

    courses = config.get('courses', [])
    term = config.get('term', '202601')  # Default to Fall 2024 if not specified

    if not courses:
        logging.info("No courses to check. Exiting.")
        return

    logging.info(f"Checking availability for courses: {courses}")
    
    driver = setup_driver()
    
    try:
        # Navigate to the course selection page
        load_webpage(driver, "https://vsb.mcgill.ca/criteria.jsp?access=0&lang=en&tip=0&page=results&scratch=0&advice=0&legend=1&term=202601&sort=none&filters=iiiiiiiiii&bbs=&ds=&cams=DOWNTOWN_OFF-CAMPUS_DISTANCE_MACDONALD&locs=any&isrts=any&ses=any&pl=&pac=1&course_0_0=FACC-300&va_0_0=e602&sa_0_0=&cs_0_0=--202601_2657-2663-&cpn_0_0=&csn_0_0=&ca_0_0=&dropdown_0_0=al&ig_0_0=0&rq_0_0=&bg_0_0=0&cr_0_0=&ss_0_0=0&sbc_0_0=0")

        # Check availability for each course
        logging.info("Checking course availability...")
        available_courses = {}
        for course in courses:
            available_sections = get_course_availability(driver, course)
            if available_sections:
                # available_courses[course] = available_sections
                logging.info(f"Course {course} is available:")
                for crn, availability_type in available_sections:
                    if crn == '2657':
                        available_courses[course] = available_sections
                    logging.info(f"  CRN: {crn}, Availability: {availability_type}")
            else:
                logging.info(f"Course {course} is not available")

        # Send notification if any courses are available
        if available_courses:
            notification_title = "Course Availability Alert"
            notification_body = "The following courses are available:\n"
            for course, sections in available_courses.items():
                notification_body += f"{course}:\n"
                for crn, availability_type in sections:
                    notification_body += f"  CRN: {crn}, Availability: {availability_type}\n"
            send_notification(notification_title, notification_body)
        else:
            logging.info("No courses are currently available.")

        logging.info("All courses have been checked for availability.")
    except Exception as e:
        logging.error(f"An error occurred during web task: {str(e)}")
        logging.debug("Traceback:\n%s", traceback.format_exc())
    finally:
        driver.quit()

if __name__ == "__main__":
    perform_web_task()
