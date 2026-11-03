import os
import json
import requests
from typing import TypedDict
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from ddgs import DDGS

# Load Environment Variables
load_dotenv()

app = Flask(__name__)

# ==========================================
# 1. INITIALIZE LLM (Gemini Free Tier)
# ==========================================
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash", 
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# ==========================================
# HELPER FUNCTION (Fixes Array/String issue)
# ==========================================
def get_text_content(response):
    """Ensures we always get a clean string from the LLM response."""
    content = response.content
    if isinstance(content, list):
        return "".join([part.get('text', '') if isinstance(part, dict) else str(part) for part in content])
    return str(content)

# ==========================================
# 2. DEFINE TOOLS FOR AGENTS
# ==========================================

@tool
def search_hotels_with_links(destination: str) -> str:
    """Searches for hotels in the destination and returns raw data with prices and links."""
    try:
        ddgs = DDGS()
        # Specific query to get prices and links
        query = f"hotels in {destination} price per night booking link"
        results = list(ddgs.text(query, max_results=8))
        
        hotels_raw = []
        for r in results:
            # Format: Title | URL | Snippet (which often contains price info)
            hotels_raw.append(f"Title: {r['title']} | Link: {r['href']} | Details: {r['body']}")
        
        return "\n".join(hotels_raw) if hotels_raw else "No hotels found via search."
    except Exception as e:
        return f"Search failed: {str(e)}"

@tool
def calculate_fuel_cost(distance_km: float, vehicle_type: str) -> str:
    """Calculates the estimated petrol/diesel cost for the trip."""
    mileage = 45.0 if vehicle_type.lower() == "bike" else 15.0
    fuel_price = 105.0 
    
    fuel_needed = distance_km / mileage
    total_cost = fuel_needed * fuel_price
    
    return (f"Vehicle: {vehicle_type.capitalize()}\n"
            f"Distance: {distance_km} km\n"
            f"Estimated Mileage: {mileage} km/l\n"
            f"Fuel Needed: {fuel_needed:.2f} liters\n"
            f"Estimated Fuel Cost: ₹{total_cost:.2f}")

@tool
def get_live_weather(location: str, start_date: str, end_date: str) -> str:
    """Fetches LIVE daily weather forecast for a location between start_date and end_date."""
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=en&format=json"
        geo_res = requests.get(geo_url).json()
        
        if 'results' not in geo_res:
            return f"Could not find location: {location}."

        lat = geo_res['results'][0]['latitude']
        lon = geo_res['results'][0]['longitude']

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
            f"&start_date={start_date}&end_date={end_date}&timezone=auto"
        )
        weather_res = requests.get(weather_url).json()

        daily = weather_res.get('daily', {})
        dates = daily.get('time', [])
        max_temps = daily.get('temperature_2m_max', [])
        min_temps = daily.get('temperature_2m_min', [])
        weather_codes = daily.get('weathercode', [])
        rain = daily.get('precipitation_sum', [])

        wmo_codes = {
            0: "☀️ Clear Sky", 1: "🌤️ Mainly Clear", 2: "⛅ Partly Cloudy", 3: "☁️ Overcast", 
            45: "🌫️ Foggy", 48: "🌫️ Rime Fog", 
            51: "🌦️ Light Drizzle", 53: "🌦️ Moderate Drizzle", 55: "🌧️ Dense Drizzle",
            61: "🌧️ Slight Rain", 63: "🌧️ Moderate Rain", 65: "🌧️ Heavy Rain",
            71: "🌨️ Slight Snow", 73: "🌨️ Moderate Snow", 75: "❄️ Heavy Snow",
            80: "🌦️ Slight Rain Showers", 81: "🌧️ Moderate Rain Showers", 82: "⛈️ Violent Rain Showers",
            95: "⛈️ Thunderstorm", 96: "⛈️ Thunderstorm with Hail"
        }

        forecast = []
        for i in range(len(dates)):
            code = weather_codes[i]
            desc = wmo_codes.get(code, "🌍 Unknown Weather")
            rain_val = rain[i] if rain[i] > 0 else 0
            forecast.append(
                f"- **{dates[i]}**: {desc} | 🌡️ High: {max_temps[i]}°C / Low: {min_temps[i]}°C | 🌧️ Rain: {rain_val}mm"
            )

        return "\n".join(forecast) if forecast else "No weather data available."

    except Exception as e:
        return f"Live weather fetch failed: {str(e)}"

# ==========================================
# 3. DEFINE MULTI-AGENT STATE & NODES
# ==========================================

class TravelState(TypedDict):
    from_loc: str
    to_loc: str
    vehicle: str
    start_date: str
    end_date: str
    destination_info: str
    logistics_info: str
    booking_info: str
    final_plan: str

def research_agent(state: TravelState):
    prompt = f"""
    You are an expert Travel Researcher. 
    Destination: {state['to_loc']}
    Travel Dates: {state['start_date']} to {state['end_date']}
    
    Provide a detailed description of {state['to_loc']}. 
    Include: Top 5 best places to visit, local culture, and a day-by-day itinerary.
    """
    response = llm.invoke(prompt)
    return {"destination_info": get_text_content(response)}

def logistics_agent(state: TravelState):
    dist_prompt = f"What is the approximate road distance in kilometers between {state['from_loc']} and {state['to_loc']}? Reply with ONLY the number."
    dist_response = llm.invoke(dist_prompt)
    try:
        distance = float(''.join(filter(lambda x: x.isdigit() or x == '.', get_text_content(dist_response))))
    except:
        distance = 500.0

    fuel_cost = calculate_fuel_cost.invoke({"distance_km": distance, "vehicle_type": state['vehicle']})
    
    route_prompt = f"""
    You are a Route Planning Expert. Plan a road trip from {state['from_loc']} to {state['to_loc']}.
    1. Suggest the best and shortest route.
    2. Mention any scenic shortcuts.
    3. Suggest 3-4 best food stops/dhabas along this specific route.
    """
    route_response = llm.invoke(route_prompt)
    
    return {"logistics_info": f"### 🗺️ Route & Fuel Details\n{get_text_content(route_response)}\n\n### ⛽ Fuel Calculation\n{fuel_cost}"}

def booking_agent(state: TravelState):
    # 1. Get RAW hotel data from DuckDuckGo
    raw_hotels = search_hotels_with_links.invoke({"destination": state['to_loc']})

    # 2. Use LLM to SORT hotels from LOW to HIGH price and format with links
    sort_prompt = f"""
    You are a hotel booking expert. Here is a raw list of hotels with their details and links:
    {raw_hotels}

    TASK:
    1. Extract the hotel name, approximate price, and the booking link from the raw data.
    2. SORT the hotels from LOWEST price to HIGHEST price.
    3. Format the output as a clean Markdown list. 
    
    FORMAT RULE:
    - **[Hotel Name](Booking_Link)** - ₹Approx Price/night - *1-line description*
    
    If exact price is not in the text, estimate it based on the hotel type (Budget, Mid-range, Luxury) and sort accordingly.
    """
    sorted_hotels_response = llm.invoke(sort_prompt)
    sorted_hotels = get_text_content(sorted_hotels_response)

    # 3. Get LIVE Weather
    live_weather = get_live_weather.invoke({
        "location": state['to_loc'],
        "start_date": state['start_date'],
        "end_date": state['end_date']
    })
    
    return {
        "booking_info": f"### 🌤️ Live Weather Forecast (Real-time Data)\n{live_weather}\n\n### 🏨 Hotels & Lodges (Sorted: Low to High Price)\n{sorted_hotels}"
    }

def synthesizer_agent(state: TravelState):
    prompt = f"""
    You are a Premium Travel Concierge. Combine the following information into a beautiful, well-structured Markdown travel plan.
    
    1. Destination Info: {state['destination_info']}
    2. Logistics & Fuel: {state['logistics_info']}
    3. Booking & Weather: {state['booking_info']}
    
    Format it beautifully with emojis, clear headings, and bullet points. Make it look like a premium travel brochure.
    """
    response = llm.invoke(prompt)
    return {"final_plan": get_text_content(response)}

# ==========================================
# 4. BUILD LANGGRAPH WORKFLOW
# ==========================================

workflow = StateGraph(TravelState)

workflow.add_node("researcher", research_agent)
workflow.add_node("logistics", logistics_agent)
workflow.add_node("booking", booking_agent)
workflow.add_node("synthesizer", synthesizer_agent)

workflow.set_entry_point("researcher")
workflow.add_edge("researcher", "logistics")
workflow.add_edge("logistics", "booking")
workflow.add_edge("booking", "synthesizer")
workflow.add_edge("synthesizer", END)

travel_graph = workflow.compile()

# ==========================================
# 5. FLASK ROUTES
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/plan', methods=['POST'])
def plan_trip():
    try:
        data = request.json
        initial_state = {
            "from_loc": data.get('from_loc'),
            "to_loc": data.get('to_loc'),
            "vehicle": data.get('vehicle'),
            "start_date": data.get('start_date'),
            "end_date": data.get('end_date'),
            "destination_info": "",
            "logistics_info": "",
            "booking_info": "",
            "final_plan": ""
        }

        final_state = travel_graph.invoke(initial_state)
        return jsonify({"success": True, "plan": final_state["final_plan"]})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)