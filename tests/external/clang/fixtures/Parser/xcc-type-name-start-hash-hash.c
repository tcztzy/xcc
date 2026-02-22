int main(void){ int x = 0; return _Generic(x, ##: 1, default: 0); }
