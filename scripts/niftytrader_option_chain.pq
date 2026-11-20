let
    // NiftyTrader Credentials & Configuration (Replace with your active key/token)
    BearerToken = "YOUR_NIFTYTRADER_BEARER_TOKEN",
    ApiKey      = "YOUR_NIFTYTRADER_API_KEY",
    ApiUrl      = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse",

    // Fetch API Data
    Source = Json.Document(
        Web.Contents(
            ApiUrl,
            [
                Headers = [
                    #"Authorization"   = "Bearer " & BearerToken,
                    #"x-api-key"       = ApiKey,
                    #"Accept"          = "application/json, text/plain, */*",
                    #"Accept-Encoding" = "gzip, deflate",
                    #"Accept-Language" = "en-US,en;q=0.9",
                    #"User-Agent"      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
                    #"Referer"         = "https://www.niftytrader.in/",
                    #"Origin"          = "https://www.niftytrader.in"
                ],
                ManualStatusHandling = {400, 401, 403, 500}
            ]
        )
    ),

    // Safe extraction of records
    resultData = Record.FieldOrDefault(Source, "resultData", null),
    opDatas    = if resultData <> null then Record.FieldOrDefault(resultData, "opDatas", {}) else {},

    // Convert list to table
    #"Converted to Table" = Table.FromList(opDatas, Splitter.SplitByNothing(), null, null, ExtraValues.Error),

    // Expand record fields (clean column names without "Column1." prefix)
    #"Expanded Columns" = Table.ExpandRecordColumn(
        #"Converted to Table",
        "Column1",
        {
            "symbol_name", "expiry_date", "strike_price", "index_close", 
            "pcr", "change_oi_pcr", "volume_pcr", "created_at", "time",
            // Calls
            "calls_oi", "calls_change_oi", "calls_volume", "calls_iv", "calls_ltp", 
            "calls_net_change", "calls_bid_price", "calls_ask_price", "calls_open", 
            "calls_high", "calls_low", "calls_offer_price", "calls_oi_value", 
            "calls_change_oi_value", "calls_average_price", "previous_eod_calls_oi", 
            "calls_change_oi_per", "calls_ltp_per", "call_delta", "call_gamma", 
            "call_vega", "call_theta", "call_rho", "calls_builtup", "calls_intrisic", 
            "calls_time_value", "calls_bid_quantity", "calls_offer_quantity", 
            "calls_iv_eod", "calls_high_eod", "calls_low_eod",
            // Puts
            "puts_oi", "puts_change_oi", "puts_volume", "puts_iv", "puts_ltp", 
            "puts_net_change", "puts_bid_price", "puts_ask_price", "puts_open", 
            "puts_high", "puts_low", "puts_offer_price", "puts_oi_value", 
            "puts_change_oi_value", "puts_average_price", "previous_eod_puts_oi", 
            "puts_change_oi_per", "puts_ltp_per", "put_delta", "put_gamma", 
            "put_vega", "put_theta", "put_rho", "puts_builtup", "puts_intrisic", 
            "puts_time_value", "puts_bid_quantity", "puts_offer_quantity", 
            "puts_iv_eod", "puts_high_eod", "puts_low_eod"
        }
    ),

    // Strongly Type All Columns
    #"Typed Table" = Table.TransformColumnTypes(
        #"Expanded Columns",
        {
            // General Info
            {"symbol_name", type text},
            {"expiry_date", type date},
            {"created_at", type date},
            {"time", type text},
            {"strike_price", type number},
            {"index_close", type number},
            {"pcr", type number},
            {"change_oi_pcr", type number},
            {"volume_pcr", type number},

            // Calls - Quantities & Counts (Integer)
            {"calls_oi", Int64.Type},
            {"calls_change_oi", Int64.Type},
            {"calls_volume", Int64.Type},
            {"previous_eod_calls_oi", Int64.Type},
            {"calls_bid_quantity", Int64.Type},
            {"calls_offer_quantity", Int64.Type},

            // Calls - Prices, Greeks & Analytics (Decimal / Number)
            {"calls_ltp", type number},
            {"calls_net_change", type number},
            {"calls_ltp_per", type number},
            {"calls_iv", type number},
            {"calls_iv_eod", type number},
            {"calls_open", type number},
            {"calls_high", type number},
            {"calls_low", type number},
            {"calls_bid_price", type number},
            {"calls_ask_price", type number},
            {"calls_offer_price", type number},
            {"calls_average_price", type number},
            {"calls_oi_value", type number},
            {"calls_change_oi_value", type number},
            {"calls_change_oi_per", type number},
            {"calls_intrisic", type number},
            {"calls_time_value", type number},
            {"calls_high_eod", type number},
            {"calls_low_eod", type number},
            {"calls_builtup", type text},
            {"call_delta", type number},
            {"call_gamma", type number},
            {"call_vega", type number},
            {"call_theta", type number},
            {"call_rho", type number},

            // Puts - Quantities & Counts (Integer)
            {"puts_oi", Int64.Type},
            {"puts_change_oi", Int64.Type},
            {"puts_volume", Int64.Type},
            {"previous_eod_puts_oi", Int64.Type},
            {"puts_bid_quantity", Int64.Type},
            {"puts_offer_quantity", Int64.Type},

            // Puts - Prices, Greeks & Analytics (Decimal / Number)
            {"puts_ltp", type number},
            {"puts_net_change", type number},
            {"puts_ltp_per", type number},
            {"puts_iv", type number},
            {"puts_iv_eod", type number},
            {"puts_open", type number},
            {"puts_high", type number},
            {"puts_low", type number},
            {"puts_bid_price", type number},
            {"puts_ask_price", type number},
            {"puts_offer_price", type number},
            {"puts_average_price", type number},
            {"puts_oi_value", type number},
            {"puts_change_oi_value", type number},
            {"puts_change_oi_per", type number},
            {"puts_intrisic", type number},
            {"puts_time_value", type number},
            {"puts_high_eod", type number},
            {"puts_low_eod", type number},
            {"puts_builtup", type text},
            {"put_delta", type number},
            {"put_gamma", type number},
            {"put_vega", type number},
            {"put_theta", type number},
            {"put_rho", type number}
        }
    )
in
    #"Typed Table"
