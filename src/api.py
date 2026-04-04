"""
FastAPI backend for Stock Trend Tracker
Provides REST API endpoints for:
1. Update stock financial data
2. Calculate and filter stocks meeting requirements
3. Query top stocks by valuation metrics
4. Query individual stock valuation
"""

import os
import sys
import json
import glob
import asyncio
from datetime import datetime
from typing import Optional, List
from pathlib import Path

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import existing modules
from query_data_new import (
    get_stock_list,
    query_data,
    load_metadata,
    save_metadata,
    should_query_financial,
    should_query_price,
    query_financial_data_incremental,
    query_price_data_incremental,
    AUTO_DETECT_STOCK_TYPES,
    HARDCODED_STOCK_TYPES
)
from calculation_and_visualization_new import (
    get_stock_codes,
    calculate_stock_values,
    find_and_visualize_best_stocks
)
from query_top_stocks import (
    load_all_stocks_valuation,
    find_top_stocks,
    get_stock_name
)
from query_stock_valuation import (
    load_stock_valuation,
    calculate_quantiles
)

# Create FastAPI app
app = FastAPI(
    title="Stock Trend Tracker API",
    description="API for stock valuation analysis and data management",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Mount static files
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Global state for background tasks
task_status = {
    "update_data": {"status": "idle", "message": "", "progress": 0},
    "calculate_stocks": {"status": "idle", "message": "", "progress": 0}
}


# ============== Pydantic Models ==============

class UpdateDataRequest(BaseModel):
    data_type: str  # 'financial' or 'price'
    stock_type: str  # 'hs300', 'zz500', 'hongli', etc.
    force: bool = False
    adjust: str = ""  # 'qfq', 'hfq', or ''


class UpdateDataResponse(BaseModel):
    success: bool
    message: str
    stocks_updated: int = 0
    stocks_failed: int = 0


class CalculateStocksRequest(BaseModel):
    threshold: float = 0.26
    generate_images: bool = True


class CalculateStocksResponse(BaseModel):
    success: bool
    message: str
    total_stocks: int = 0
    filtered_stocks: int = 0
    stocks: List[dict] = []


class TopStocksResponse(BaseModel):
    success: bool
    indicator: str
    top_n: int
    total_analyzed: int
    stocks: List[dict]


class StockValuationResponse(BaseModel):
    success: bool
    stock_code: str
    stock_name: str
    latest_data: dict
    quantiles: dict
    target_prices: dict
    historical_data: List[dict]


class StockListItem(BaseModel):
    code: str
    name: str


class MetadataResponse(BaseModel):
    financial: dict
    price: dict


# ============== Helper Functions ==============

def get_base_dir():
    """Get the base directory for data files"""
    return str(BASE_DIR)


def get_stock_names_df():
    """Load stock names dataframe"""
    stock_names_file = BASE_DIR / "data" / "input" / "stock_names_full.csv"
    if stock_names_file.exists():
        return pd.read_csv(stock_names_file)
    return pd.DataFrame(columns=['code', 'name'])


# ============== API Endpoints ==============

@app.get("/")
async def root():
    """Serve the main HTML page"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Stock Trend Tracker API. Please create static/index.html"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/stock-types")
async def get_stock_types():
    """Get available stock types"""
    types = {
        "auto_detect": AUTO_DETECT_STOCK_TYPES,
        "hardcoded": list(HARDCODED_STOCK_TYPES.keys())
    }
    return {"success": True, "stock_types": types}


@app.get("/api/stock-list/{stock_type}")
async def get_stock_list_endpoint(stock_type: str):
    """Get stock list for a given type"""
    try:
        df = get_stock_list(stock_type)
        stock_names_df = get_stock_names_df()
        
        stocks = []
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            name = ""
            if not stock_names_df.empty:
                match = stock_names_df[stock_names_df['code'].astype(str).str.zfill(6) == code]
                if not match.empty:
                    name = match.iloc[0]['name']
            stocks.append({"code": code, "name": name})
        
        return {"success": True, "stock_type": stock_type, "count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/metadata")
async def get_metadata():
    """Get query metadata (last update times)"""
    try:
        # Use absolute path for metadata file
        metadata_file = BASE_DIR / "data" / "input" / "query_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        else:
            metadata = {"financial": {}, "price": {}}
        return {"success": True, "metadata": metadata}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update-data")
async def update_data(request: UpdateDataRequest, background_tasks: BackgroundTasks):
    """
    Update stock financial or price data
    This runs as a background task due to potentially long execution time
    """
    # Validate inputs
    valid_types = AUTO_DETECT_STOCK_TYPES + list(HARDCODED_STOCK_TYPES.keys())
    if request.stock_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid stock_type. Must be one of: {valid_types}"
        )
    
    if request.data_type not in ['financial', 'price']:
        raise HTTPException(
            status_code=400,
            detail="data_type must be 'financial' or 'price'"
        )
    
    # Check if task is already running
    if task_status["update_data"]["status"] == "running":
        return {
            "success": False,
            "message": "An update task is already running. Please wait.",
            "status": task_status["update_data"]
        }
    
    # Reset status
    task_status["update_data"] = {
        "status": "running",
        "message": f"Starting {request.data_type} data update for {request.stock_type}...",
        "progress": 0
    }
    
    # Run update in background
    background_tasks.add_task(
        run_update_data,
        request.data_type,
        request.stock_type,
        request.force,
        request.adjust
    )
    
    return {
        "success": True,
        "message": "Update task started in background",
        "status": task_status["update_data"]
    }


def run_update_data(data_type: str, stock_type: str, force: bool, adjust: str):
    """Background task to update data"""
    try:
        # Change to src directory for relative paths
        original_dir = os.getcwd()
        src_dir = BASE_DIR / "src"
        os.chdir(src_dir)
        
        # Get stock list
        stocks_df = get_stock_list(stock_type)
        total_stocks = len(stocks_df)
        
        task_status["update_data"]["message"] = f"Found {total_stocks} stocks to process"
        task_status["update_data"]["progress"] = 10
        
        if data_type == "financial":
            output_dir = "../data/input/financial-indicators/all"
            os.makedirs(output_dir, exist_ok=True)
            
            metadata = load_metadata()
            stock_codes = stocks_df['code'].tolist()
            
            # Count stocks needing update
            stocks_to_update = []
            for stock_code in stock_codes:
                should_query, _ = should_query_financial(metadata, str(stock_code), force)
                if should_query:
                    stocks_to_update.append(stock_code)
            
            task_status["update_data"]["message"] = f"Updating {len(stocks_to_update)} stocks..."
            task_status["update_data"]["progress"] = 20
            
            query_financial_data_incremental(stocks_df, output_dir, force=force)
            
        elif data_type == "price":
            output_dir = "../data/input/price-data/all"
            os.makedirs(output_dir, exist_ok=True)
            
            query_price_data_incremental(stocks_df, output_dir, force=force, adjust=adjust)
        
        task_status["update_data"]["status"] = "completed"
        task_status["update_data"]["message"] = f"Successfully updated {data_type} data for {stock_type}"
        task_status["update_data"]["progress"] = 100
        
        os.chdir(original_dir)
        
    except Exception as e:
        task_status["update_data"]["status"] = "failed"
        task_status["update_data"]["message"] = f"Error: {str(e)}"
        task_status["update_data"]["progress"] = 0


@app.get("/api/update-status")
async def get_update_status():
    """Get the status of the current update task"""
    return {"success": True, "status": task_status["update_data"]}


@app.post("/api/calculate-stocks")
async def calculate_stocks(request: CalculateStocksRequest, background_tasks: BackgroundTasks):
    """
    Calculate stock valuations and find stocks meeting criteria
    """
    # Check if task is already running
    if task_status["calculate_stocks"]["status"] == "running":
        return {
            "success": False,
            "message": "A calculation task is already running. Please wait.",
            "status": task_status["calculate_stocks"]
        }
    
    # Reset status
    task_status["calculate_stocks"] = {
        "status": "running",
        "message": "Starting stock valuation calculation...",
        "progress": 0,
        "threshold": request.threshold,
        "result": None
    }
    
    # Run calculation in background
    background_tasks.add_task(
        run_calculate_stocks,
        request.threshold,
        request.generate_images
    )
    
    return {
        "success": True,
        "message": "Calculation task started in background",
        "status": task_status["calculate_stocks"]
    }


def run_calculate_stocks(threshold: float, generate_images: bool):
    """Background task to calculate stock values"""
    try:
        # Change to src directory for relative paths
        original_dir = os.getcwd()
        src_dir = BASE_DIR / "src"
        os.chdir(src_dir)
        
        # Get stock codes
        stock_codes = get_stock_codes()
        total_stocks = len(stock_codes)
        
        task_status["calculate_stocks"]["message"] = f"Calculating valuations for {total_stocks} stocks..."
        task_status["calculate_stocks"]["progress"] = 10
        
        # Calculate stock values
        calculate_stock_values(stock_codes)
        
        task_status["calculate_stocks"]["message"] = "Finding best stocks..."
        task_status["calculate_stocks"]["progress"] = 50
        
        # Find and visualize best stocks
        today = datetime.now().strftime("%Y%m%d")
        
        # Load all valuation data
        stock_values = []
        for stock_value_file in os.listdir("../data/processed/stock-valuation/all"):
            if not stock_value_file.endswith('.csv'):
                continue
            stock_value = pd.read_csv(os.path.join("../data/processed/stock-valuation/all/", stock_value_file))
            stock_value['code'] = stock_value['code'].astype(int).astype(str).str.zfill(6)
            stock_values.append(stock_value.iloc[-1])
        
        stock_values_df = pd.DataFrame(stock_values, columns=stock_value.columns)
        
        # Calculate thresholds
        pe_th = stock_values_df.query("pe_ttm > 0").pe_ttm.quantile(threshold)
        pb_th = stock_values_df.query("pe_ttm > 0").pb_ttm.quantile(threshold)
        pr_th = stock_values_df.query("pe_ttm > 0").pr_ttm.quantile(threshold)
        roe_th = stock_values_df.query("pe_ttm > 0").roe_ttm.quantile(1-threshold)
        
        # Filter stocks
        filtered_df = stock_values_df.query(
            f"(pe_ttm < {pe_th}) & (pb_ttm < {pb_th}) & (pr_ttm < {pr_th}) & (roe_ttm > {roe_th})"
        )
        
        # Save filtered stocks
        filtered_df.to_csv(f"../data/processed/stock-valuation/stocks_values_filtered_{today}.csv", index=False)
        
        # Get stock names
        stock_names_df = get_stock_names_df()
        
        # Prepare result
        stocks_list = []
        for _, row in filtered_df.iterrows():
            code = str(row['code']).zfill(6)
            name = ""
            if not stock_names_df.empty:
                match = stock_names_df[stock_names_df['code'].astype(str).str.zfill(6) == code]
                if not match.empty:
                    name = match.iloc[0]['name']
            
            stocks_list.append({
                "code": code,
                "name": name,
                "close": round(row['close'], 2),
                "pe_ttm": round(row['pe_ttm'], 2),
                "pb_ttm": round(row['pb_ttm'], 2),
                "pr_ttm": round(row['pr_ttm'], 2),
                "roe_ttm": round(row['roe_ttm'], 2)
            })
        
        # Generate images if requested
        if generate_images:
            task_status["calculate_stocks"]["message"] = "Generating visualization images..."
            task_status["calculate_stocks"]["progress"] = 70
            find_and_visualize_best_stocks(threshold)
        
        task_status["calculate_stocks"]["status"] = "completed"
        task_status["calculate_stocks"]["message"] = f"Found {len(stocks_list)} stocks meeting criteria"
        task_status["calculate_stocks"]["progress"] = 100
        task_status["calculate_stocks"]["result"] = {
            "total_stocks": total_stocks,
            "filtered_stocks": len(stocks_list),
            "thresholds": {
                "pe_ttm": round(pe_th, 2),
                "pb_ttm": round(pb_th, 2),
                "pr_ttm": round(pr_th, 2),
                "roe_ttm": round(roe_th, 2)
            },
            "stocks": stocks_list
        }
        
        os.chdir(original_dir)
        
    except Exception as e:
        task_status["calculate_stocks"]["status"] = "failed"
        task_status["calculate_stocks"]["message"] = f"Error: {str(e)}"
        task_status["calculate_stocks"]["progress"] = 0


@app.get("/api/calculate-status")
async def get_calculate_status():
    """Get the status of the current calculation task"""
    return {"success": True, "status": task_status["calculate_stocks"]}


@app.get("/api/top-stocks")
async def get_top_stocks(
    indicator: str = Query("pe_ttm", description="Indicator to sort by: pe_ttm, pb_ttm, pr_ttm, roe_ttm"),
    top_n: int = Query(10, ge=1, le=100, description="Number of top stocks to return")
):
    """
    Query top N stocks by specified valuation indicator
    - pe_ttm, pb_ttm, pr_ttm: lower is better
    - roe_ttm: higher is better
    """
    valid_indicators = ['pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm']
    if indicator not in valid_indicators:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indicator. Must be one of: {valid_indicators}"
        )
    
    try:
        # Change to src directory for relative paths
        original_dir = os.getcwd()
        src_dir = BASE_DIR / "src"
        os.chdir(src_dir)
        
        # Load all stocks valuation data
        all_stocks_df = load_all_stocks_valuation()
        
        # Find top stocks
        top_stocks_df = find_top_stocks(all_stocks_df, indicator, top_n)
        
        os.chdir(original_dir)
        
        if top_stocks_df.empty:
            return {
                "success": False,
                "message": "No valid stock data found. Please run calculation first.",
                "indicator": indicator,
                "top_n": top_n,
                "total_analyzed": 0,
                "stocks": []
            }
        
        # Prepare response
        stocks_list = []
        for _, row in top_stocks_df.iterrows():
            stock_data = {
                "code": str(row['code']).zfill(6),
                "name": row.get('name', ''),
                "close": round(row.get('close', 0), 2),
                "pe_ttm": round(row.get('pe_ttm', 0), 2),
                "pb_ttm": round(row.get('pb_ttm', 0), 2),
                "pr_ttm": round(row.get('pr_ttm', 0), 2),
                "roe_ttm": round(row.get('roe_ttm', 0), 2)
            }
            stocks_list.append(stock_data)
        
        return {
            "success": True,
            "indicator": indicator,
            "top_n": top_n,
            "total_analyzed": len(all_stocks_df),
            "stocks": stocks_list
        }
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail="Valuation data not found. Please run calculation first."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock-valuation/{stock_code}")
async def get_stock_valuation(stock_code: str):
    """
    Get detailed valuation data for a specific stock
    """
    stock_code = stock_code.zfill(6)
    
    try:
        # Change to src directory for relative paths
        original_dir = os.getcwd()
        src_dir = BASE_DIR / "src"
        os.chdir(src_dir)
        
        # Load stock valuation data
        stock_df = load_stock_valuation(stock_code)
        
        # Load all stocks for quantile calculation
        all_stocks_df = load_all_stocks_valuation()
        
        # Get stock name
        stock_name = get_stock_name(stock_code)
        
        # Get latest data
        latest = stock_df.iloc[-1]
        
        # Calculate quantiles
        pe_quantile = calculate_quantiles(all_stocks_df, 'pe_ttm', latest['pe_ttm'])
        pb_quantile = calculate_quantiles(all_stocks_df, 'pb_ttm', latest['pb_ttm'])
        pr_quantile = calculate_quantiles(all_stocks_df, 'pr_ttm', latest['pr_ttm'])
        roe_quantile = calculate_quantiles(all_stocks_df, 'roe_ttm', latest['roe_ttm'])
        
        # Calculate target prices
        pr_25 = stock_df['pr_ttm'].quantile(0.25)
        pr_75 = stock_df['pr_ttm'].quantile(0.75)
        current_pr = latest['pr_ttm']
        
        price_25th = float(latest['close'] * pr_25 / current_pr) if current_pr > 0 else None
        price_75th = float(latest['close'] * pr_75 / current_pr) if current_pr > 0 else None
        
        os.chdir(original_dir)
        
        # Prepare historical data (last 24 records)
        historical = stock_df.tail(24)[['report_date', 'open', 'close', 'high', 'low', 'pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm']].copy()
        historical['report_date'] = historical['report_date'].astype(str)
        historical_data = historical.to_dict('records')
        
        return {
            "success": True,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "latest_data": {
                "report_date": str(latest['report_date']),
                "close": round(float(latest['close']), 2),
                "pe_ttm": round(float(latest['pe_ttm']), 2),
                "pb_ttm": round(float(latest['pb_ttm']), 2),
                "pr_ttm": round(float(latest['pr_ttm']), 2),
                "roe_ttm": round(float(latest['roe_ttm']), 2),
                "eps_ttm": round(float(latest.get('eps_ttm', 0)), 2),
                "bps_ttm": round(float(latest.get('bps_ttm', 0)), 2)
            },
            "quantiles": {
                "pe_ttm": round(pe_quantile * 100, 1) if pe_quantile else None,
                "pb_ttm": round(pb_quantile * 100, 1) if pb_quantile else None,
                "pr_ttm": round(pr_quantile * 100, 1) if pr_quantile else None,
                "roe_ttm": round(roe_quantile * 100, 1) if roe_quantile else None
            },
            "target_prices": {
                "current": round(float(latest['close']), 2),
                "pr_25th": round(price_25th, 2) if price_25th else None,
                "pr_75th": round(price_75th, 2) if price_75th else None,
                "upside_25th": round((price_25th / latest['close'] - 1) * 100, 1) if price_25th else None,
                "upside_75th": round((price_75th / latest['close'] - 1) * 100, 1) if price_75th else None
            },
            "historical_data": historical_data
        }
        
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Stock {stock_code} not found in valuation data."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filtered-stocks")
async def get_filtered_stocks():
    """
    Get the latest filtered stocks (stocks meeting criteria)
    """
    try:
        # Find the latest filtered stocks file
        filtered_dir = BASE_DIR / "data" / "processed" / "stock-valuation"
        filtered_files = list(filtered_dir.glob("stocks_values_filtered_*.csv"))
        
        if not filtered_files:
            return {
                "success": False,
                "message": "No filtered stocks data found. Please run calculation first.",
                "stocks": []
            }
        
        # Get the latest file
        latest_file = max(filtered_files, key=lambda x: x.stat().st_mtime)
        df = pd.read_csv(latest_file)
        
        # Get stock names
        stock_names_df = get_stock_names_df()
        
        # Prepare response
        stocks_list = []
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            name = ""
            if not stock_names_df.empty:
                match = stock_names_df[stock_names_df['code'].astype(str).str.zfill(6) == code]
                if not match.empty:
                    name = match.iloc[0]['name']
            
            stocks_list.append({
                "code": code,
                "name": name,
                "close": round(row.get('close', 0), 2),
                "pe_ttm": round(row.get('pe_ttm', 0), 2),
                "pb_ttm": round(row.get('pb_ttm', 0), 2),
                "pr_ttm": round(row.get('pr_ttm', 0), 2),
                "roe_ttm": round(row.get('roe_ttm', 0), 2)
            })
        
        return {
            "success": True,
            "file_date": latest_file.stem.split('_')[-1],
            "total_stocks": len(stocks_list),
            "stocks": stocks_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/images/{date}/{filename}")
async def get_image(date: str, filename: str):
    """Serve generated images"""
    image_path = BASE_DIR / "img" / date / filename
    if image_path.exists():
        return FileResponse(image_path)
    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/api/images-list/{date}")
async def list_images(date: str):
    """List all images for a given date"""
    img_dir = BASE_DIR / "img" / date
    if not img_dir.exists():
        return {"success": False, "message": "No images found for this date", "images": []}
    
    images = [f.name for f in img_dir.glob("*.png")]
    return {"success": True, "date": date, "images": images}


# Mount static files at the end
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)