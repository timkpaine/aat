use super::{Registry, Tracker};
use crate::common::{Float, Id};
use crate::core::Account;

use std::sync::{Arc, Mutex};

#[derive(Clone, Debug)]
pub struct AccountRegistry {
    tracker: Arc<Mutex<Tracker<Account>>>,
}

impl AccountRegistry {
    pub fn new() -> Self {
        AccountRegistry {
            tracker: Arc::new(Mutex::new(Tracker::new())),
        }
    }

    pub fn create(&self, balance: Float, instrument_id: Id) -> Account {
        let id = (*self.tracker.lock().unwrap()).next();
        let account = Account::new(id, instrument_id, Some(balance));
        *self.tracker.lock().unwrap().create(account)
    }

    pub fn set_balance(&self, account_id: Id, balance: Float) {
        let account = self.get(account_id);

        // Clone the old account into a new account
        let mut replacement_account = account;

        // update the volume
        replacement_account.set_balance(balance);

        // replace it in the Registry
        self.replace(account_id, replacement_account);
    }
}

impl Registry for AccountRegistry {
    type Item = Account;

    fn get(&self, id: Id) -> Self::Item {
        *self.tracker.lock().unwrap().get(id)
    }

    fn remove(&self, id: Id) -> Self::Item {
        self.tracker.lock().unwrap().remove(id)
    }

    fn replace(&self, id: Id, item: Self::Item) {
        self.tracker.lock().unwrap().replace(id, item)
    }
}
