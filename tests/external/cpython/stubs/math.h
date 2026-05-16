#ifndef _MATH_H
#define _MATH_H

double fabs(double x);
double sqrt(double x);
double pow(double x, double y);
double exp(double x);
double log(double x);
double log10(double x);
double sin(double x);
double cos(double x);
double tan(double x);
double floor(double x);
double ceil(double x);
double round(double x);
double fmod(double x, double y);
double frexp(double x, int *exp);
double ldexp(double x, int exp);
double modf(double x, double *iptr);
int isinf(double x);
int isnan(double x);
int isfinite(double x);
double log1p(double x);
double hypot(double x, double y);
double copysign(double x, double y);
double acosh(double x);
double asinh(double x);
double atanh(double x);
double erf(double x);
double erfc(double x);
double expm1(double x);
double log2(double x);
double cbrt(double x);
double atan2(double y, double x);

#define M_PI 3.14159265358979323846
#define INFINITY __builtin_inff()
#define NAN __builtin_nanf("")
#define HUGE_VAL __builtin_inff()

#endif
