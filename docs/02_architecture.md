# Architecture

## High-level architecture

```text

+----------------------+         +------------------------+

| sample\_fund\_guidelines | --> | deterministic graph     |

+----------------------+         | rule seed / chunks      |

                                 +------------------------+

                                         |

                                         v

+----------------------+       +------------------------+

| sample\_holdings.csv   | --> | Knowledge Graph         |

+----------------------+       | NetworkX MultiDiGraph   |

                              +------------------------+

                                         |

                                         v

                              +------------------------+

                              | Deterministic Compute   |

                              | Engine                  |

                              +------------------------+

                                         |

                   +---------------------+---------------------+

                   |                     |                     |

                   v                     v                     v

            figures.json          report.xlsx          reconciliation.json

                   |                     |                     |

                   +----------+----------+---------------------+

                              |

                              v

                   +------------------------+

                   | Append-only Audit Log  |

                   | SQLite + triggers      |

                   +------------------------+

```

