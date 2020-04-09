#include <aat/core/order_book/price_level.hpp>

namespace aat {
namespace core {
  PriceLevel::PriceLevel(double price, Collector& collector)
    : price(price)
    , collector(collector) {}

  double
  PriceLevel::getVolume() const {
    double sum = 0.0;
    for (Order* order : orders) {
      sum += (order->volume - order->filled);
    }
    return sum;
  }

  void
  PriceLevel::add(Order* order) {
    // append order to deque
    if (order->order_type == OrderType::STOP) {
      if (std::find(orders.begin(), orders.end(), order) != orders.end()) {
        return;
      }
      orders.push_back(order);
    } else {
      if (std::find(orders.begin(), orders.end(), order) != orders.end()) {
        collector.pushChange(order);
      } else {
        // change event
        orders.push_back(order);
        collector.pushOpen(order);
      }
    }
  }

  Order*
  PriceLevel::remove(Order* order) {
    // check if order is in level
    if (order->price != price || std::find(orders.begin(), orders.end(), order) == orders.end()) {
      // something is wrong
      throw AATCPPException("Order note found in price level!");
    }
    // remove order
    orders.erase(std::find(orders.begin(), orders.end(), order)); // FIXME c++

    // trigger cancel event
    collector.pushCancel(order);

    // return the order
    return order;
  }

  Order*
  PriceLevel::cross(Order* taker_order) {
    if (taker_order->order_type == OrderType::STOP) {
      add(taker_order);
      return nullptr; //, ()
    }

    if (taker_order->filled >= taker_order->volume) {
      // already filled
      return nullptr; //, _get_stop_orders()
    }

    while (taker_order->filled < taker_order->volume && orders.size() > 0) {
      // need to fill original volume - filled so far
      double to_fill = taker_order->volume - taker_order->filled;

      // pop maker order from list
      Order* maker_order = orders.front();
      orders.pop_front();

      // add to staged in case we need to revert
      orders_staged.push_back(maker_order);

      // remaining in maker_order
      double maker_remaining = maker_order->volume - maker_order->filled;

      if (maker_remaining > to_fill) {
        // handle fill or kill/all or nothing
        if (maker_order->flag == OrderFlag::FILL_OR_KILL || maker_order->flag == OrderFlag::ALL_OR_NONE) {
          // kill the maker order and continue
          collector.pushCancel(maker_order);
          continue;
        } else {
          // maker_order is partially executed
          maker_order->filled += to_fill;

          // will exit loop
          taker_order->filled = taker_order->volume;
          collector.pushFill(taker_order);

          // change event
          collector.pushChange(maker_order, true);

          if (maker_order->flag == OrderFlag::IMMEDIATE_OR_CANCEL) {
            // cancel maker event, don't put in queue
            collector.pushCancel(maker_order);
          } else {
            // push back in deque
            orders.push_front(maker_order);
          }
        }
      } else if (maker_remaining < to_fill) {
        // partially fill it regardles
        // this will either trigger the revert in order_book,
        // or it will be partially executed
        taker_order->filled += maker_remaining;

        if (taker_order->flag == OrderFlag::ALL_OR_NONE) {
          // taker order can't be filled, push maker back and cancel taker
          // push back in deque
          orders.push_front(maker_order);
          return nullptr; //, self._get_stop_orders()
        } else {
          // maker_order is fully executed
          // don't append to deque
          // tell maker order filled
          collector.pushChange(taker_order);
          collector.pushFill(maker_order, true);
        }
      } else {
        // exactly equal
        maker_order->filled += to_fill;
        taker_order->filled += maker_remaining;

        collector.pushFill(taker_order);
        collector.pushFill(maker_order, true);
      }
    }

    if (taker_order->filled >= taker_order->volume) {
      // execute the taker order
      collector.pushTrade(taker_order);

      // return nothing to signify to stop
      return nullptr; //, self._get_stop_orders()
    }

    // return order, this level is cleared and the order still has volume
    return taker_order; //, self._get_stop_orders()
  }

  void
  PriceLevel::clear() {
    orders.clear();
    orders_staged.clear();
    stop_orders.clear();
    stop_orders_staged.clear();
  }

  void
  PriceLevel::commit() {
    clear();
  }

  void
  PriceLevel::revert() {
    orders = orders_staged;
    orders_staged = std::deque<Order*>();
    stop_orders = stop_orders_staged;
    stop_orders_staged = std::vector<Order*>();
  }

} // namespace core
} // namespace aat