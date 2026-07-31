#ifndef __WAITRADE_TYPES_MQH__
#define __WAITRADE_TYPES_MQH__

// 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
// WaiTrade2 EA 鈥?鏍稿績鏁版嵁缁撴瀯
// 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

#define MAX_OB_ZONES   100
#define MAX_POSITIONS  20
#define OB_BUY         1
#define OB_SELL       -1

struct OBZone
{
    double   high;           // OB鍖哄煙涓婃部
    double   low;            // OB鍖哄煙涓嬫部
    double   mid;            // 鍏ュ満浠?(鍖哄煙涓偣)
    int      direction;      // OB_BUY=鐪嬫定(鍋氬), OB_SELL=鐪嬭穼(鍋氱┖)
    datetime created;        // 鍒涘缓鏃堕棿
    int      created_bar;    // 鍒涘缓鏃剁殑鍏ㄥ眬bar璁℃暟
    int      touch_count;    // 浠锋牸瑙︾OB鍖哄煙娆℃暟
    datetime first_touch;    // 棣栨瑙︾鏃堕棿
    datetime last_touch;     // 鏈€杩戣Е纰版椂闂?
    double   strength;       // OB寮哄害璇勫垎 (1.0-5.0)
    bool     is_fresh;       // 鏄惁鏈瑙︾杩?
    bool     is_continuation;// 鏄惁椤哄娍OB
    bool     is_1h_aligned;  // 鏄惁涓?H OB鏂瑰悜涓€鑷?
    double   ds_weight;      // 渚涢渶鏉冮噸 (0.5-2.5)
    int      entry_count;    // 宸插熀浜庤OB鍏ュ満娆℃暟
    datetime last_entry_time;// 鏈€杩戜竴娆″熀浜庤OB鍏ュ満鏃堕棿
    bool     used;           // 鏄惁宸插叆鍦?
    bool     expired;        // 鏄惁宸茶繃鏈?
    bool     is_range_breakout; // 鏄惁涓洪渿鑽″尯闂寸獊鐮翠俊鍙?
    bool     is_liquidity_sweep; // 鏄惁涓烘祦鍔ㄦ€ф壂鎹熷弽杞俊鍙?
    bool     is_loose_sweep; // loose sweep supplemental signal
    bool     is_htf_pullback; // higher-timeframe net-push pullback signal
    double   range_height;    // 闇囪崱鍖洪棿楂樺害锛岀敤浜庨噺搴︾洰鏍?
    double   ob_top;          // OB妫€娴嬪師濮嬮《閮?瀹炰綋杈圭晫)
    double   ob_bottom;       // OB妫€娴嬪師濮嬪簳閮?瀹炰綋杈圭晫)
};

struct TradeSignal
{
    int      direction;      // 1=鍋氬, -1=鍋氱┖
    double   entry;          // 鍏ュ満浠?(OB mid)
    double   sl;             // 姝㈡崯浠?
    double   tp;             // 姝㈢泩浠?(0=DTP妯″紡)
    double   risk_price;     // 椋庨櫓璺濈 (|entry - sl|)
    double   lot;            // 璁＄畻鎵嬫暟
    double   pos_mult;       // 浠撲綅涔樻暟
    int      ob_index;       // 瀵瑰簲OB鏁扮粍绱㈠紩
    bool     deep_entry;      // 鏄惁娣卞叆OB鍚庡叆鍦?
    double   touch_price;     // EntryEngine鐪熷疄瑙︾偣/鏈€娣辫Е鐐?
    double   confirm_price;   // EntryEngine纭浠?
    int      bounce_seconds;  // 浠庤Е鐐瑰埌纭鑰楁椂
    double   bounce_ob_pct;   // 纭鍙嶅脊骞呭害/OB楂樺害
    double   confirm_body_pct;
    double   confirm_ob_pos;  // 纭浠风浉瀵筄B鍖洪棿浣嶇疆(涔?楂樹簬涓婃部涓烘,鍗?浣庝簬涓嬫部涓烘)
    bool     htf_target;      // 鏄惁浣跨敤澶у懆鏈熺洰鏍囦綅
    double   htf_partial_r;   // 澶у懆鏈熺洰鏍囧崟鍒嗘壒R
    int      htf_partial_pct; // 澶у懆鏈熺洰鏍囧崟鍒嗘壒姣斾緥
    bool     failure_reverse; // 鏄惁澶辫触鍙嶆墜鍗?
    string   comment;        // 璁㈠崟澶囨敞
};

struct PosTrack
{
    ulong    ticket;         // 鎸佷粨ticket
    int      direction;      // 1=澶? -1=绌?
    double   entry_price;    // 鍏ュ満浠?
    double   sl_initial;     // 鍒濆姝㈡崯
    double   risk_price;     // 鍒濆椋庨櫓璺濈
    double   peak_profit_r;  // 鍘嗗彶鏈€楂樻诞鐩?R鍊嶆暟)
    int      open_bar;       // 寮€浠撴椂鐨勫叏灞€bar璁℃暟
    bool     be_applied;     // 鏄惁宸叉墽琛屼繚鏈?
    int      trail_level;    // 褰撳墠杩借釜绾у埆 (0=鏃? 1-3)
    bool     dtp_active;     // DTP鏄惁宸叉縺娲?
    double   dtp_peak_r;     // DTP婵€娲诲悗鐨勫嘲鍊糝
    bool     partial_closed; // 鏄惁宸叉墽琛岄儴鍒嗗钩浠?
    bool     dtp_partial_closed; // DTP鏄惁宸叉墽琛岄儴鍒嗗钩浠?
    bool     deep_entry;      // 鏄惁娣卞叆OB鍚庡叆鍦?
    bool     htf_target;      // 鏄惁浣跨敤澶у懆鏈熺洰鏍囦綅
    double   htf_partial_r;   // 澶у懆鏈熺洰鏍囧崟鍒嗘壒R
    int      htf_partial_pct; // 澶у懆鏈熺洰鏍囧崟鍒嗘壒姣斾緥
    bool     failure_reverse; // 鏄惁澶辫触鍙嶆墜鍗?
    int      addon_count;     // 宸茶Е鍙戝己鍔垮欢缁姞浠撴鏁?
    bool     strong_addon;    // 鏄惁寮哄娍寤剁画鍔犱粨鍗?
    datetime last_close_attempt; // 鏈€杩戜竴娆′富鍔ㄥ競浠峰钩浠撳皾璇曟椂闂?
    string   last_sl_reason; // 鏈€杩戜竴娆L淇敼鏉ユ簮
    double   virtual_sl;
    string   virtual_sl_reason;
    int      entry_market_state; // 鍏ュ満鏃跺競鍦虹姸鎬?1=bull,-1=bear,0=range)
};

struct EAState
{
    int      bar_count;      // 鍏ㄥ眬bar璁℃暟鍣?(浠嶦A鍚姩寮€濮嬬疮鍔?
    int      last_entry_bar; // 涓婃鍏ュ満鐨刡ar璁℃暟 (鐢ㄤ簬cooldown)
    int      ob_count;       // 褰撳墠鏈夋晥OB鏁伴噺
    int      pos_count;      // 褰撳墠璺熻釜鐨勬寔浠撴暟閲?
    double   atr_value;      // 褰撳墠ATR鍊?
    double   atr_1h;         // 1H ATR鍊?
    // v9.8
    int      market_state;   // MARKET_STATE enum value (1=bull, -1=bear, 0=range)
    double   target_price;   // 闇囪崱鎬佸闈wing鐐逛环鏍?
    double   atr_m15;        // M15 ATR
};

#endif
