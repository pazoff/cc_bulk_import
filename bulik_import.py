import os
import requests
from typing import Dict
from cat.mad_hatter.decorators import tool, hook, plugin
from cat.looking_glass.stray_cat import StrayCat
from cat.log import log
from threading import Thread
from multiprocessing import cpu_count
from enum import Enum
from pydantic import BaseModel

class BatchSize(Enum):
    auto: str = "Auto"
    one: int = 1
    two: int = 2
    three: int = 3
    four: int = 4
    

class BulkImportSettings(BaseModel):
    # Select
    files_to_ingest_simultaneously: BatchSize = BatchSize.one

# Give your settings model to the Cat.
@plugin
def settings_model():
    return BulkImportSettings


@hook(priority=10)
def agent_fast_reply(fast_reply, cat) -> Dict:
    return_direct = False
    # Get user message
    user_message = cat.working_memory["user_message_json"]["text"]

    if user_message.startswith("bulkimport url"):
        response = bulk_url_import(user_message.split(" ")[2], cat)
        return_direct = True

    if user_message.startswith("bulkimport docs"):
        # Use threading for bulk_docs_import
        thread = Thread(target=bulk_docs_import_thread, args=(cat,))
        thread.start()
        return_direct = True
        response = "Bulk document import process started."

    # Manage response
    if return_direct:
        return {"output": response}

    return fast_reply

# Define bulk_docs_import_thread to run bulk_docs_import in a separate thread
def bulk_docs_import_thread(cat):
    response = bulk_docs_import(cat)
    cat.send_ws_message(content=response, msg_type='chat')

    # Save the response to ingested_files.html
    with open('/app/cat/static/bulkimport/ingested_files.html', 'w', encoding='utf-8') as file:
        file.write(response)

def bulk_url_import(url_list: str, cat):
    message = '<table><thead><tr><th class="text-neutral">URL</th><th class="text-neutral">Status</th></tr></thead><tbody>'
    for link in url_list.split(","):
        if not link.startswith(("http://", "https://")):
            message = (
                message
                + link
                + ": Invalid link format: must start with 'http://' or 'https://'\n"
            )
        else:
            try:
                parsed_link = requests.get(link).url
                log("Send " + parsed_link + " to rabbithole", "WARNING")
                # Use threading
                tr = Thread(target=cat.rabbit_hole.ingest_file, args=(cat, parsed_link, 400, 100))
                tr.start()
                log(parsed_link + " sent to rabbithole!", "WARNING")
                message = message + "<tr><td>" + link + "</td><td>&#x2705;</td></tr>"
            except requests.exceptions.RequestException as err:
                message = (
                    message
                    + "<tr><td>"
                    + link
                    + "</td><td>&#x274C; "
                    + str(err)
                    + "</td></tr>"
                )
    message = message + "</tbody></table>"
    return message

def bulk_docs_import(cat):

    # Load the settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    get_batch_size = settings.get("files_to_ingest_simultaneously")

    # Set default values if not provided
    if get_batch_size == "Auto":
        batch_size = max(1, cpu_count() // 2)
    elif get_batch_size is None:
        get_batch_size = 1
    else:
        batch_size = int(get_batch_size)

    message = '<table><thead><tr><th class="text-neutral">Document</th><th class="text-neutral">Status</th></tr></thead><tbody>'
    files = os.listdir("/app/cat/static/bulkimport")

    num_files_ingested = 0
    for i in range(0, len(files), batch_size):
        current_batch = files[i:i+batch_size]
        ingestion_threads = []

        cat.send_ws_message(content=f"Ingesting {batch_size} more files simultaneously ...", msg_type='chat')

        for idx, file in enumerate(current_batch, 1):
            if file.startswith("."):
                continue
            try:
                log("Send " + file + " to rabbithole", "WARNING")
                filepath = "/app/cat/static/bulkimport/" + file
                t = Thread(target=cat.rabbit_hole.ingest_file, args=(cat, filepath, 400, 100))
                t.start()
                num_files_ingested += 1
                # Add the thread to the list
                ingestion_threads.append(t)
                log(file + " sent to rabbithole!", "WARNING")
                message += "<tr><td>" + file + "</td><td>&#x2705;</td></tr>"

                # Send progress message
                progress_message = f"{idx}. <b>{file}</b> successfully sent to rabbithole."
                cat.send_ws_message(content=progress_message, msg_type='chat')

                # Check if we've started batch_size threads
                if idx % batch_size == 0:
                    # Join all the threads to wait for all URLs to be ingested
                    for t in ingestion_threads:
                        t.join()

                    # Delete the files after successful ingestion
                    # for f in current_batch:
                    #     file_path_to_delete = os.path.join("/app/cat/static/bulkimport/", f)
                    #     os.remove(file_path_to_delete)
                    
                    cat.send_ws_message(content=f"Ingested <b>{str(current_batch)[1:-1]}</b>.<br>{len(files) - num_files_ingested} more files to go ...", msg_type='chat')

            except requests.exceptions.RequestException as err:
                message += "<tr><td>" + file + "</td><td>&#x274C; " + str(err) + "</td></tr>"

                # Send error message
                error_message = f"Error sending {file} to rabbithole: {str(err)}"
                cat.send_ws_message(content=error_message, msg_type='chat')

    
    message += "</tbody></table>"
    return message
