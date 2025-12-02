import json
import matplotlib.pyplot as plt
from datetime import datetime
from PIL import Image
import io

def plot_scores_to_image(predictions_history: dict) -> Image.Image:
    """
    Parses the event data and plots the historical and predicted scores, 
    returning the plot as a PIL Image object.

    Args:
        predictions_history: A dictionary containing the API response data, including 
                  'event_name', 'history', and 'predictions'.

    Returns:
        A PIL.Image.Image object containing the rendered plot.
    """
    try:
        data = predictions_history['data']
        event_name = data['event_name']
        event_id = data['event_id']
        rank = data['rank']
        history_data = data['history']
        predictions_data = data['predictions']
        current_score = data['current_score']
        predicted_score = data['predicted_score']

        # --- 1. Prepare Data for Plotting ---
        
        # Historical Data
        history_times = [datetime.fromisoformat(item['t'].replace('Z', '+00:00')).astimezone() for item in history_data]
        history_scores = [item['y'] for item in history_data]

        # Predicted Data
        prediction_times = [datetime.fromisoformat(item['t'].replace('Z', '+00:00')).astimezone() for item in predictions_data]
        prediction_scores = [item['y'] for item in predictions_data]

        # --- 2. Create the Plot ---
        
        # Set a figure size that works well for displaying a plot
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot Historical Data
        ax.plot(history_times, history_scores, label='历史分数', color='blue', marker='o', markersize=3, linestyle='-')

        # Plot Predicted Data
        ax.plot(prediction_times, prediction_scores, label='历史预测', color='red', linestyle='--')

        # Add horizontal line for the final current score
        if history_times:
            final_time = history_times[-1]
            final_score = history_scores[-1]
            ax.axhline(y=final_score, color='green', linestyle=':', label=f'当前分数: {final_score:,}')
            # ax.scatter(final_time, final_score, color='green', zorder=5, label='Last Recorded Point')
            
        # Add horizontal line for the final predicted score
        if prediction_scores:
            final_pred_score = prediction_scores[-1]
            ax.axhline(y=final_pred_score, color='purple', linestyle='-.', label=f'当前预测: {final_pred_score:,}')

        # --- 3. Customize the Plot ---

        ax.set_title(f'{event_id} {event_name} t{rank} 历史预测线', fontsize=16)
        ax.set_xlabel('时间', fontsize=12)
        ax.set_ylabel('分数', fontsize=12)
        
        # Format y-axis labels to include commas for thousands separator
        ax.ticklabel_format(style='plain', axis='y')
        ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, p: format(int(x), ',')))
        
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend()
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout() # Adjust layout to prevent labels from overlapping

        # --- 4. Convert Plot to PIL Image ---

        # Save the plot to a BytesIO object in PNG format
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)  # Close the figure to free up memory

        # Seek to the beginning of the buffer and open it with PIL
        buf.seek(0)
        img = Image.open(buf)
        
        return img

    except KeyError as e:
        print(f"Error: Missing key in API data: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

# Example Usage (assuming the provided JSON data is loaded into a variable)
# Note: You would need to load your file content here.
# For demonstration, I'll use a placeholder for the file content:

"""
api_data_from_file = {
    "success": true,
    "timestamp": 1764610815329,
    "data": {
        "current_score": 52203146,
        "event_id": 149,
        "event_name": "The Power Of Regret",
        ... (rest of your data)
    }
}
"""

# To run this example, you would first load your JSON file:
with open('predictions-149-100.json', 'r') as f:
    predictions_history = json.load(f)

# Uncomment the following lines to test the function if you have the data loaded
# if 'api_data_from_file' in locals():
plot_image = plot_scores_to_image(predictions_history)
if plot_image:
    plot_image.save('predictions-149-100.png') # To display the image (requires a display environment)
    # Or save it to a file: plot_image.save('score_plot.png')