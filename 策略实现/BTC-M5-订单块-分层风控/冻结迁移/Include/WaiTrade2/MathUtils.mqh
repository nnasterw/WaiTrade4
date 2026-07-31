#ifndef __WAITRADE_MATH_UTILS_MQH__
#define __WAITRADE_MATH_UTILS_MQH__

#include "Config.mqh"

double CalcATR(const MqlRates &rates[], int count, int period=14)
{
   if(count < period + 1) return 0.0;
   double sum = 0.0;
   for(int i = count - period; i < count; i++)
   {
      double tr = rates[i].high - rates[i].low;
      double tr2 = MathAbs(rates[i].high - rates[i-1].close);
      double tr3 = MathAbs(rates[i].low - rates[i-1].close);
      if(tr2 > tr) tr = tr2;
      if(tr3 > tr) tr = tr3;
      sum += tr;
   }
   return sum / period;
}

double PriceToR(double price, double entry, double risk_price, int direction)
{
   if(risk_price <= 0) return 0.0;
   return (price - entry) * direction / risk_price;
}

double RToPrice(double r_value, double entry, double risk_price, int direction)
{
   return entry + r_value * risk_price * direction;
}

ENUM_TIMEFRAMES GetWorkTF()
{
   switch(CfgBarTF())
   {
      case 1:   return PERIOD_M1;
      case 2:   return PERIOD_M2;
      case 3:   return PERIOD_M3;
      case 4:   return PERIOD_M4;
      case 5:   return PERIOD_M5;
      case 6:   return PERIOD_M6;
      case 10:  return PERIOD_M10;
      case 12:  return PERIOD_M12;
      case 15:  return PERIOD_M15;
      case 20:  return PERIOD_M20;
      case 30:  return PERIOD_M30;
      case 60:  return PERIOD_H1;
      case 240: return PERIOD_H4;
      default:  return PERIOD_M1;
   }
}

ENUM_TIMEFRAMES MinutesToTF(int minutes)
{
   switch(minutes)
   {
      case 1:   return PERIOD_M1;
      case 2:   return PERIOD_M2;
      case 3:   return PERIOD_M3;
      case 4:   return PERIOD_M4;
      case 5:   return PERIOD_M5;
      case 6:   return PERIOD_M6;
      case 10:  return PERIOD_M10;
      case 12:  return PERIOD_M12;
      case 15:  return PERIOD_M15;
      case 20:  return PERIOD_M20;
      case 30:  return PERIOD_M30;
      case 60:  return PERIOD_H1;
      case 240: return PERIOD_H4;
      default:  return PERIOD_M15;
   }
}

#endif
