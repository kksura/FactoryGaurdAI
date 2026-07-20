// Cost guardrail (spec §13): monthly budget filtered to the spoke RG with
// actual + forecast alerts. Budgets never stop resources — the alert emails
// plus the cost-anomaly review in the runbook are the response path.

targetScope = 'subscription'

param namePrefix string
param resourceGroupName string
param amount int
param startDate string
param contactEmails array

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'budget-${namePrefix}'
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [resourceGroupName]
      }
    }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: contactEmails
      }
      actual100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: contactEmails
      }
      forecast110: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 110
        thresholdType: 'Forecasted'
        contactEmails: contactEmails
      }
    }
  }
}
