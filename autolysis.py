# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "argparse",
#     "fastapi",
#     "logging",
#     "matplotlib",
#     "openai",
#     "pandas",
#     "scikit-learn",
#     "scipy",
#     "seaborn",
#     "uvicorn",
#     "requests",
# ]
# ///
import argparse
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
import io
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import json
import os
import logging
from scipy.stats import zscore
import requests

# Set up logging
logging.basicConfig(level=logging.INFO)

# Define a function to parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Process CSV file.")
    parser.add_argument("csv_file", type=str, help="Path to the CSV file")
    return parser.parse_args()

# Define a function to read a CSV file
def read_csv(filepath):
    try:
        # Try reading the file with utf-8 encoding
        return pd.read_csv(filepath, encoding="utf-8")
    except UnicodeDecodeError:
        # If there's a UnicodeDecodeError, try reading the file with a different encoding
        return pd.read_csv(filepath, encoding="latin1")

# Define a function to generate a summary of a DataFrame
def generate_summary(df: pd.DataFrame) -> dict:
    buffer = io.StringIO()
    df.info(buf=buffer)
    summary = {
        "info": buffer.getvalue(),
        "description": df.describe().to_string(),
        "missing_values": (df.isnull().sum().to_string()),
    }
    return summary

# Parse command-line arguments and read the CSV file
args = parse_args()
df = read_csv(args.csv_file)

# Initialize OpenAI API (requires a valid API token in environment variables)
api_token = os.getenv("AIPROXY_TOKEN")
if not api_token:
    logging.error("OpenAI API token is not configured. Set 'AIPROXY_TOKEN' in your environment.")
    exit(1)

def call_openai_api(input_messages, model="gpt-4o-mini"):
    """
    Call the OpenAI API to process data and log the raw response for debugging.
    """
    url = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": input_messages,
        "functions": [
            {
                "name": "suggest_columns",
                "description": "Suggest relevant columns for clustering or correlation analysis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["columns"],
                },
            }
        ],
        "function_call": {"name": "suggest_columns"},
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Decode the response JSON
        result = response.json()
        
        # Log the raw response for debugging
        #logging.info("OpenAI API Raw Response: %s", json.dumps(result, indent=4))

        # Process and validate the API response
        return process_openai_response(result)
    except requests.exceptions.RequestException as req_error:
        logging.error(f"Request error: {req_error}")
        raise
    except json.JSONDecodeError as json_error:
        logging.error(f"JSON decode error: {json_error}")
        raise
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        raise

def process_openai_response(result):
    """
    Process the JSON-decoded response from the OpenAI API.
    """
    try:
        # Ensure 'choices' exists and is not empty
        if "choices" in result and len(result["choices"]) > 0:
            choice = result["choices"][0]
            
            # Check for 'message' in the first choice
            if "message" in choice and choice["message"]:
                message = choice["message"]
                
                # Handle 'function_call' if present
                if "function_call" in message:
                    function_call = message["function_call"]
                    arguments_str = function_call.get("arguments", None)
                    
                    if arguments_str:
                        try:
                            # Decode JSON arguments
                            arguments = json.loads(arguments_str)
                            return arguments  # Return successfully parsed arguments
                        except json.JSONDecodeError as e:
                            logging.error(f"Error decoding JSON: {e}")
                            return {"error": "Invalid JSON in function_call arguments"}
                    
                    return {"error": "No arguments found in function_call"}
                
                # Handle 'content' if no 'function_call'
                elif "content" in message and message["content"] is not None:
                    return {"content": message["content"]}
                else:
                    return {"error": "No usable content or function call in response"}
            else:
                return {"error": "No message found in choices"}
        else:
            return {"error": "OpenAI response does not contain 'choices' field or it is empty"}
    
    except KeyError as e:
        logging.error(f"KeyError: {e}")
        return {"error": f"Missing key: {e}"}
    except Exception as e:
        logging.error(f"Unhandled exception in processing: {e}")
        return {"error": str(e)}

def analyze_with_openai(summary: dict, analysis_type: str):
    """
    Send the data summary to OpenAI for analysis and get a structured response.
    """
    prompt = f"Given the following data summary: {summary}, suggest columns for {analysis_type} in JSON format."
    input_messages = [
        {"role": "system", "content": "You are an AI that performs data analysis."},
        {"role": "user", "content": prompt},
    ]

    try:
        response = call_openai_api(input_messages)
        # Parse the JSON response
        return response  # Return structured JSON data
    except json.JSONDecodeError as jde:
        logging.error(f"Error decoding JSON from OpenAI response: {jde}")
        return {"error": "Invalid JSON response"}
    except Exception as e:
        logging.error(f"Error in OpenAI analysis ({analysis_type}): {e}")
        return {"error": str(e)}

# Set global style for visualizations
sns.set_theme(style="whitegrid", palette="pastel")
plt.rcParams.update({
    'axes.titlesize': 10,
    'axes.labelsize': 8,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'legend.fontsize': 8,
    'figure.figsize': (6, 6)
})

def generate_bubble_map(df: pd.DataFrame, clustering_response: dict):
    """
    Generate and save a bubble map based on clustering columns.

    Args:
        df (pd.DataFrame): The input DataFrame containing data for clustering.
        clustering_response (dict): A dictionary containing clustering column information.

    Returns:
        str: The file path of the saved bubble map image.
    """
    try:
        if "columns" in clustering_response:
            clustering_columns = clustering_response["columns"]

        if clustering_columns and isinstance(clustering_columns, list) and all(col in df.columns for col in clustering_columns):
            df_selected = df[clustering_columns]
            if df_selected.isnull().any().any():
                logging.warning("NaN values detected. Imputing missing values with column means.")
                df_selected = df_selected.fillna(df_selected.mean())

            df_normalized = df_selected.apply(zscore)

            kmeans = KMeans(n_clusters=3, random_state=42)
            df_normalized['Cluster'] = kmeans.fit_predict(df_normalized)

            plt.figure(figsize=(8, 8))
            sns.scatterplot(
                data=df_normalized,
                x=clustering_columns[0],
                y=clustering_columns[1],
                hue='Cluster',
                size=clustering_columns[2] if len(clustering_columns) > 2 else None,
                sizes=(50, 300),
                palette='viridis',
                alpha=0.7
            )
            plt.title("Bubble Map for Clustering", fontsize=16, fontweight='bold')
            plt.xlabel(clustering_columns[0], fontsize=12)
            plt.ylabel(clustering_columns[1], fontsize=12)
            plt.legend(title="Cluster", loc="upper right")

            file_path = "clustering_bubble_map.png"
            plt.savefig(file_path, bbox_inches='tight')
            plt.close()

            logging.info("Bubble map generated and saved successfully.")
            return file_path
        else:
            logging.warning("Suggested clustering columns are invalid or missing in the DataFrame.")
            return None
    except Exception as e:
        logging.error(f"Error generating bubble map: {e}")
        return None

def generate_barplot(df: pd.DataFrame, barplot_response: dict):
    """
    Generate and save a barplot based on the specified columns.

    Args:
        df (pd.DataFrame): The input DataFrame containing data for analysis.
        barplot_response (dict): A dictionary containing column information for the barplot.

    Returns:
        str: The file path of the saved barplot image.
    """
    try:
        if "columns" in barplot_response:
            barplot_columns = barplot_response["columns"]

        if barplot_columns and isinstance(barplot_columns, list) and all(col in df.columns for col in barplot_columns):
            x_col = barplot_columns[0]
            y_col = barplot_columns[1] if len(barplot_columns) > 1 else None

            if y_col is None:
                logging.warning("Barplot requires at least two columns: one for x and one for y.")
                return None

            df_selected = df[[x_col, y_col]].dropna()

            plt.figure(figsize=(10, 6))
            sns.barplot(data=df_selected, x=x_col, y=y_col, palette="coolwarm")
            plt.title("Barplot Analysis", fontsize=16, fontweight='bold')
            plt.xlabel(x_col, fontsize=12)
            plt.ylabel(y_col, fontsize=12)

            file_path = "barplot_analysis.png"
            plt.savefig(file_path, bbox_inches='tight')
            plt.close()

            logging.info("Barplot generated and saved successfully.")
            return file_path
        else:
            logging.warning("Suggested columns are invalid or missing in the DataFrame.")
            return None
    except Exception as e:
        logging.error(f"Error generating barplot: {e}")
        return None

def generate_correlation_heatmap(df: pd.DataFrame, correlation_response: dict):
    """
    Generate and save a correlation heatmap based on the specified columns.

    Args:
        df (pd.DataFrame): The input DataFrame containing data for analysis.
        correlation_response (dict): A dictionary containing column information for the correlation heatmap.

    Returns:
        str: The file path of the saved heatmap image.
    """
    try:
        if isinstance(correlation_response, dict) and "columns" in correlation_response:
            columns = correlation_response["columns"]

            if columns and isinstance(columns, list) and all(col in df.columns for col in columns):
                df_selected = df[columns]

                corr_matrix = df_selected.corr()

                plt.figure(figsize=(10, 8))
                sns.heatmap(corr_matrix, annot=True, cmap="coolwarm", linewidths=0.5, fmt='.2f')
                plt.title("Correlation Heatmap", fontsize=16, fontweight='bold')
                plt.tight_layout()

                file_path = "correlation_heatmap.png"
                plt.savefig(file_path, bbox_inches='tight')
                plt.close()

                logging.info("Heatmap generated and saved successfully.")
                return file_path
            else:
                logging.warning("Suggested columns are invalid or missing in the DataFrame.")
                return None
        else:
            logging.warning("The correlation response does not contain the expected key 'columns'.")
            return None
    except Exception as e:
        logging.error(f"Error generating correlation heatmap: {e}")
        return None

def generate_line_chart(df: pd.DataFrame, time_series_response: dict):
    """
    Generate and save a line chart based on the specified columns for time series analysis.

    Args:
        df (pd.DataFrame): The input DataFrame containing data for analysis.
        time_series_response (dict): A dictionary containing column information for the time series plot.

    Returns:
        str: The file path of the saved line chart image.
    """
    try:
        if isinstance(time_series_response, dict) and "columns" in time_series_response:
            columns = time_series_response["columns"]

            if columns and isinstance(columns, list) and all(col in df.columns for col in columns):
                df_selected = df[columns]

                plt.figure(figsize=(12, 6))
                for column in columns:
                    plt.plot(df_selected.index, df_selected[column], label=column, linewidth=2)

                plt.title("Time Series Line Chart", fontsize=16, fontweight='bold')
                plt.xlabel("Date", fontsize=12)
                plt.ylabel("Value", fontsize=12)
                plt.legend(title="Variables", loc="upper left")
                plt.tight_layout()

                file_path = "time_series_line_chart.png"
                plt.savefig(file_path, bbox_inches='tight')
                plt.close()

                logging.info("Line chart generated and saved successfully.")
                return file_path
            else:
                logging.warning("Suggested columns are invalid or missing in the DataFrame.")
                return None
        else:
            logging.warning("The time series response does not contain the expected key 'columns'.")
            return None
    except Exception as e:
        logging.error(f"Error generating line chart: {e}")
        return None
    
def call_openai_api_for_story(summary, plot_file_paths, model="gpt-4o-mini"):
    """
    Call the OpenAI API to generate a compelling story with a detailed analysis
    of the provided summary and plot images.
    """
    url = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    # api_token = {api_token}  # Replace with your actual API token
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # System message defines the assistant's behavior
    system_message = {
        "role": "system",
        "content": (
            "You are a highly skilled financial analyst and storyteller. "
            "Your task is to create detailed, insightful, and engaging narratives from summaries, "
            "data plots, and trend observations. Use descriptive language to explain the insights clearly, "
            "compare data trends, highlight patterns, and suggest implications of the analysis."
        ),
    }

    # User's prompt with the summary
    user_summary_message = {
        "role": "user",
        "content": (
            f"Here is a detailed summary of the financial data:{summary}\n\n"
            "Analyze the trends, patterns, anomalies, and key insights described in this summary. "
            "Compare different data points, highlight relationships between variables, and explore any contrasts or changes "
            "in the data over time. Formulate an in-depth analysis that captures the essence of this summary."
        ),
    }

    # Adding plot file paths to the context
    plot_context = "\n".join([f"Plot {i+1}: {path}" for i, path in enumerate(plot_file_paths)])
    user_plots_message = {
        "role": "user",
        "content": (
            "The following plots are associated with the analysis:\n"
            f"{plot_context}\n\n"
            "Please incorporate detailed observations from these plots into your analysis and story. "
            "For each plot, describe its key features, relationships, and trends it represents. "
            "Connect the observations from the plots to the findings in the summary and analyze how they "
            "support, contrast, or expand upon the summary data."
        ),
    }

    # Combined analysis request
    analysis_request_message = {
        "role": "user",
        "content": (
            "Based on the summary and plot data, craft a cohesive and compelling narrative. "
            "Your story should also include the following. Include relavant data points in each analysis for more compelling story:"
            "1. Provide a high-level overview of the trends and observations.\n"
            "2. Compare and contrast key data points, highlighting notable differences or similarities.\n"
            "3. Explain the implications of the trends and anomalies for decision-making or forecasting.\n"
            "4. Seamlessly integrate both the summary and plot observations into a unified story.\n"
            "5. Use an engaging and descriptive tone that is easy to follow for both financial experts and general readers.\n"
            "6. Analysis of each plot. Correlation Heatmap Analysis, Clustering Analysis, Barplot analysis, Time series analysis."
        ),
    }

    # Payload to send to the API
    payload = {
        "model": model,
        "messages": [
            system_message, 
            user_summary_message, 
            user_plots_message, 
            analysis_request_message
        ],
    }

    try:
        # Send the request to the OpenAI API
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Decode the response JSON
        result = response.json()

        # Log the raw response for debugging
        logging.info("OpenAI API Raw Response: %s", json.dumps(result, indent=4))

        # Extract and return the story content
        story_content = result["choices"][0]["message"]["content"]
        return story_content

    except requests.exceptions.RequestException as req_error:
        logging.error(f"Request error: {req_error}")
        raise
    except json.JSONDecodeError as json_error:
        logging.error(f"JSON decode error: {json_error}")
        raise
    except KeyError as key_error:
        logging.error(f"Unexpected API response structure: {key_error}")
        raise
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        raise


def write_story_to_readme(story, plot_file_paths):
    """
    Write the generated story along with the plot images to a README.md file.
    """
    with open("README.md", "w") as readme_file:
        readme_file.write("# Analysis Report\n\n")
        readme_file.write(story)
        readme_file.write("\n\n## Plot Images\n\n")

        for path in plot_file_paths:
            readme_file.write(f"![Plot Image]({path})\n\n")

    logging.info("Story and images written to README.md successfully.")

# Initialize FastAPI app
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def display_summary():
    try:
        #logging.info("Generating summary...")
        summary = generate_summary(df)
        #logging.info("Summary generated.")

        correlation_response = analyze_with_openai(summary, "correlation analysis")
        clustering_response = analyze_with_openai(summary, "clustering analysis")
        barplot_response = analyze_with_openai(summary, "barplot analysis")
        time_series_response = analyze_with_openai(summary, "time series analysis")

        correlation_map = generate_correlation_heatmap(df, correlation_response)
        bubble_map = generate_bubble_map(df, clustering_response)
        barplot = generate_barplot(df, barplot_response)
        line_chart = generate_line_chart(df, time_series_response)

        # Collect plot file paths, only if they are not None
        plot_file_paths = [
            path for path in [correlation_map, bubble_map, barplot, line_chart] if path is not None
            ]


        try:
            # Call the OpenAI API to generate the story
            story = call_openai_api_for_story(summary, plot_file_paths)

            # Write the story and plot images to README.md
            write_story_to_readme(story, plot_file_paths)
        except Exception as e:
            logging.error(f"Failed to generate story and write to README.md: {e}")


        return f"""
        <h1>Data Analysis Summary</h1>
        <h2>Summary Info:</h2>
        <pre>{summary["info"]}</pre>
        <h2>Missing Values:</h2>
        <pre>{summary["missing_values"]}</pre>
        <h2>Correlation Columns:</h2>
        <pre>{correlation_response["columns"]}</pre>
        <h2>Clustering Suggested Columns:</h2>
        <pre>{clustering_response["columns"]}</pre>
        <h2>Correlation Heatmap:</h2>
        <img src="correlation_heatmap.png" alt="Correlation Heatmap" />
        """
    except Exception as e:
        logging.error(f"Error in summary generation: {e}")
        return f"<h1>Error:</h1><p>{e}</p>"

if __name__ == "__main__":
    display_summary()

    
